import asyncio
from telegram import Update, InputFile
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from bot import messages
from bot.keyboards import main_menu
from database import db
from utils.helpers import extract_urls, human_delay
from utils.logger import get_logger
from utils.screenshot import take_screenshot
from automation.browser import StealthBrowser
from automation.qwiklabs import QwikLabsSession
from automation.cloud_console import CloudConsole

log = get_logger("Handlers")
job_lock = asyncio.Lock()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.register_user(user.id, user.username or user.first_name)
    await update.message.reply_text(
        messages.WELCOME, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu()
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(messages.WELCOME, parse_mode=ParseMode.MARKDOWN)


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    jobs = await db.get_user_jobs(user.id, limit=5)
    if not jobs:
        await update.message.reply_text("📭 لا توجد مهام سابقة.")
        return
    lines = []
    for jid, status, created in jobs:
        emoji = {"pending": "⏳", "done": "✅", "failed": "❌",
                 "waiting_password": "🔑"}.get(status, "❔")
        lines.append(messages.JOB_LINE.format(
            id=jid, status_emoji=emoji, status=status, date=created
        ))
    await update.message.reply_text(
        messages.STATUS_TEMPLATE.format(count=len(jobs), jobs="\n".join(lines)),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.clear_session(user.id)
    await update.message.reply_text("🚫 تم الإلغاء.")


async def send_photo(msg, filepath, caption=""):
    try:
        if not filepath:
            return
        with open(filepath, "rb") as f:
            await msg.reply_photo(photo=InputFile(f), caption=caption[:1000])
    except Exception as e:
        log.error(f"فشل إرسال الصورة: {e}")


# ====== الدخول: SSO ======
async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    urls = extract_urls(text)
    if not urls:
        await update.message.reply_text(messages.NO_URL)
        return
    sso_url = urls[0]
    user = update.effective_user
    if "skills.google" not in sso_url and "qwiklabs" not in sso_url:
        await update.message.reply_text("⚠️ الرابط لا يبدو من Google Skills.")
        return

    existing = await db.get_session(user.id)
    if existing:
        await update.message.reply_text(
            "⚠️ عندك مهمة قيد التنفيذ. أرسل `/cancel` باش تلغيها.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    job_id = await db.add_job(user.id, sso_url)
    await db.set_session(user.id, job_id, sso_url, None, "opening_sso")

    msg = await update.message.reply_text(
        f"📥 تم استلام المهمة `#{job_id}`\n\n🔹 جاري فتح SSO...",
        parse_mode=ParseMode.MARKDOWN,
    )
    asyncio.create_task(run_step1_open_sso(job_id, sso_url, msg, user.id, context))


# ====== الخطوة 1: فتح SSO + username ======
async def run_step1_open_sso(job_id, sso_url, msg, user_id, context):
    async with job_lock:
        browser = StealthBrowser()
        try:
            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n🔹 إطلاق المتصفح المخفي...",
                parse_mode=ParseMode.MARKDOWN,
            )
            ctx = await browser.start()

            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n🔹 فتح رابط SSO...",
                parse_mode=ParseMode.MARKDOWN,
            )
            ql = QwikLabsSession(ctx)
            page = await ql.open_sso(sso_url)

            shot = await take_screenshot(page, "01_sso")
            if shot:
                await send_photo(msg, shot, "📸 1. بعد فتح SSO")

            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n🔹 استخراج username...",
                parse_mode=ParseMode.MARKDOWN,
            )
            username = await ql.extract_credentials(page)

            shot = await take_screenshot(page, "02_username")
            if shot:
                await send_photo(msg, shot, f"📸 2. username: `{username}`")

            context.bot_data[f"page_{user_id}"] = page
            context.bot_data[f"browser_{user_id}"] = browser
            context.bot_data[f"ctx_{user_id}"] = ctx

            await db.set_session(user_id, job_id, sso_url, username, "waiting_password")

            await msg.edit_text(
                f"✅ *#{job_id}*\n\n"
                f"👤 *username:* `{username}`\n\n"
                f"🔑 *أرسل كلمة السر الآن*\n"
                f"(انسخها من صفحة Lab)",
                parse_mode=ParseMode.MARKDOWN,
            )

        except Exception as e:
            log.exception("فشل فتح SSO")
            await db.update_job(job_id, "failed", str(e))
            await db.clear_session(user_id)
            await msg.edit_text(
                messages.FAILED.format(error=str(e)[:300]),
                parse_mode=ParseMode.MARKDOWN,
            )
            try:
                await browser.close()
            except Exception:
                pass


# ====== الخطوة 2: password ======
async def handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    password = (update.message.text or "").strip()

    session = await db.get_session(user.id)
    if not session or session[3] != "waiting_password":
        return

    job_id, sso_url, username, _ = session

    try:
        await update.message.delete()
    except Exception:
        pass

    msg = await update.message.reply_text(
        f"✅ تم استلام كلمة السر\n\n🔹 جاري تسجيل الدخول...",
        parse_mode=ParseMode.MARKDOWN,
    )

    asyncio.create_task(run_step2_login(
        job_id, username, password, msg, user.id, context
    ))


# ====== الخطوة 2 الفعلية ======
async def run_step2_login(job_id, username, password, msg, user_id, context):
    async with job_lock:
        try:
            page = context.bot_data.get(f"page_{user_id}")
            browser = context.bot_data.get(f"browser_{user_id}")
            if not page:
                raise RuntimeError("الجلسة انتهت. أرسل SSO من جديد.")

            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n🔹 تسجيل الدخول لـ Cloud Console...",
                parse_mode=ParseMode.MARKDOWN,
            )
            cc = CloudConsole(page.context)
            console_page = await cc.login(username, password)

            shot = await take_screenshot(console_page, "03_console_login")
            if shot:
                await send_photo(msg, shot, "📸 3. بعد تسجيل الدخول")

            # ✅ نستنى شوية باش الصفحة تكمل التحميل
            await asyncio.sleep(5)

            project_id = await get_project_id(console_page, username)
            if not project_id:
                shot = await take_screenshot(console_page, "04_no_project")
                if shot:
                    await send_photo(
                        msg, shot,
                        f"❌ تعذر استخراج project ID\nURL: {console_page.url[:200]}"
                    )
                raise RuntimeError(
                    f"تعذر استخراج project ID\nURL: {console_page.url[:200]}"
                )

            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n"
                f"🔹 استخراج access token...\n"
                f"📦 `{project_id}`",
                parse_mode=ParseMode.MARKDOWN,
            )

            from automation.cloudrun_deployer import CloudRunDeployer, extract_access_token
            try:
                token = await extract_access_token(console_page)
            except Exception as e:
                shot = await take_screenshot(console_page, "05_token_error")
                if shot:
                    await send_photo(msg, shot, f"❌ فشل التوكن\n{str(e)[:300]}")
                raise

            shot = await take_screenshot(console_page, "06_token_ok")
            if shot:
                await send_photo(msg, shot, "📸 4. تم استخراج التوكن")

            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n"
                f"🔹 نشر `ahmed-vip1`...\n"
                f"⏳ 1-3 دقائق",
                parse_mode=ParseMode.MARKDOWN,
            )

            deployer = CloudRunDeployer(
                access_token=token,
                project_id=project_id,
                region="us-central1",
            )
            url = await deployer.deploy(
                service_name="ahmed-vip1",
                image="docker.io/ajndjd2/ahmed-vip1",
                memory="4Gi",
                cpu="2",
                port=8080,
                allow_unauthenticated=True,
            )

            try:
                await console_page.goto(
                    f"https://console.cloud.google.com/run/detail/"
                    f"{deployer.region}/ahmed-vip1?project={project_id}",
                    wait_until="domcontentloaded",
                )
                await asyncio.sleep(5)
                shot = await take_screenshot(console_page, "07_deployed")
                if shot:
                    await send_photo(msg, shot, "📸 5. Cloud Run بعد النشر")
            except Exception:
                pass

            await db.update_job(job_id, "done", url)
            await db.clear_session(user_id)

            await msg.edit_text(
                f"✅ *#{job_id}* — تم النشر بنجاح!\n\n"
                f"🔗 *الرابط:*\n{url}\n\n"
                f"👤 `{username}`\n"
                f"📦 `{project_id}`",
                parse_mode=ParseMode.MARKDOWN,
            )

        except Exception as e:
            log.exception("فشل النشر")
            await db.update_job(job_id, "failed", str(e))
            await db.clear_session(user_id)
            await msg.edit_text(
                messages.FAILED.format(error=str(e)[:300]),
                parse_mode=ParseMode.MARKDOWN,
            )
        finally:
            browser = context.bot_data.pop(f"browser_{user_id}", None)
            context.bot_data.pop(f"page_{user_id}", None)
            context.bot_data.pop(f"ctx_{user_id}", None)
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass


# ====== استخراج project_id ======
async def get_project_id(page, username: str = None) -> str:
    import re

    # 1. من URL
    url = page.url
    m = re.search(r'project=([a-z0-9\-]+)', url)
    if m:
        return m.group(1)

    # 2. من API
    try:
        pid = await page.evaluate("""
            async () => {
                try {
                    const res = await fetch(
                        'https://cloudresourcemanager.googleapis.com/v1/projects',
                        { credentials: 'include' }
                    );
                    const data = await res.json();
                    if (data.projects && data.projects.length > 0) {
                        return data.projects[0].projectId;
                    }
                } catch(e) {}
                return null;
            }
        """)
        if pid:
            log.info(f"✅ project_id من API: {pid}")
            return pid
    except Exception as e:
        log.warning(f"فشل API: {e}")

    # 3. من Home
    try:
        await page.goto(
            "https://console.cloud.google.com/home/dashboard",
            wait_until="domcontentloaded",
        )
        await human_delay(3, 5)
        m = re.search(r'project=([a-z0-9\-]+)', page.url)
        if m:
            return m.group(1)

        pid = await page.evaluate("""
            () => {
                const el = document.querySelector('[data-project-id]');
                if (el) return el.getAttribute('data-project-id');
                for (let i = 0; i < localStorage.length; i++) {
                    const k = localStorage.key(i);
                    if (k && k.includes('project')) {
                        const v = localStorage.getItem(k);
                        const m = v && v.match(/[a-z]+-[a-z0-9]+-[0-9]+/);
                        if (m) return m[0];
                    }
                }
                return null;
            }
        """)
        if pid:
            return pid
    except Exception as e:
        log.warning(f"فشل استخراج من Home: {e}")

    return None


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "status":
        await status_cmd(update, context)
    elif query.data == "help":
        await query.message.reply_text(messages.WELCOME, parse_mode=ParseMode.MARKDOWN)
