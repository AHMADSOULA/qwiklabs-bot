import asyncio
import re
from telegram import Update, InputFile
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from bot import messages
from bot.keyboards import main_menu
from database import db
from utils.helpers import extract_urls
from utils.logger import get_logger
from utils.screenshot import take_screenshot
from automation.browser import StealthBrowser
from automation.qwiklabs import QwikLabsSession
from automation.cloud_console import CloudConsole

log = get_logger("Handlers")
job_lock = asyncio.Lock()

# ==================== إعدادات ثابتة ====================
IMAGE = "docker.io/ajndjd2/ahmed-vip1"
SERVICE_NAME = "ahmed-vip1"
REGION = "us-central1"
MEMORY = "2Gi"
CPU = "2"
PORT = 8080


# ==================== أوامر ====================

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
    b = context.bot_data.pop(f"browser_{user.id}", None)
    context.bot_data.pop(f"page_{user.id}", None)
    context.bot_data.pop(f"ctx_{user.id}", None)
    if b:
        try:
            await b.close()
        except Exception:
            pass
    await update.message.reply_text("🚫 تم الإلغاء.")


async def send_photo(msg, filepath, caption=""):
    """يرسل صورة فـ تليجرام مع معالجة الأخطاء"""
    try:
        if not filepath:
            log.warning("لا يوجد مسار للصورة")
            return False
        import os
        if not os.path.exists(filepath):
            log.warning(f"الصورة ما كايناش: {filepath}")
            return False

        with open(filepath, "rb") as f:
            await msg.reply_photo(photo=InputFile(f), caption=caption[:1000])
        log.info(f"✅ تم إرسال الصورة: {filepath}")
        return True
    except Exception as e:
        log.error(f"فشل إرسال الصورة {filepath}: {e}")
        return False


# ==================== استقبال SSO ====================

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
    await db.set_session(
        user_id=user.id, job_id=job_id, sso_url=sso_url, state="opening_sso"
    )

    msg = await update.message.reply_text(
        f"📥 تم استلام المهمة `#{job_id}`\n\n🔹 جاري فتح SSO...",
        parse_mode=ParseMode.MARKDOWN,
    )
    asyncio.create_task(run_step1_open_sso(job_id, sso_url, msg, user.id, context))


# ==================== Step 1 ====================

async def run_step1_open_sso(job_id, sso_url, msg, user_id, context):
    async with job_lock:
        browser = StealthBrowser()
        try:
            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n🔹 إطلاق المتصفح...",
                parse_mode=ParseMode.MARKDOWN,
            )
            ctx = await browser.start()

            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n🔹 فتح SSO...",
                parse_mode=ParseMode.MARKDOWN,
            )
            ql = QwikLabsSession(ctx)
            page = await ql.open_sso(sso_url)

            # 📸 إرسال Screenshot بعد SSO
            shot = await take_screenshot(page, "sso_opened")
            if shot:
                await send_photo(msg, shot, "📸 بعد فتح SSO")

            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n🔹 استخراج البيانات...",
                parse_mode=ParseMode.MARKDOWN,
            )
            email, password = await ql.extract_credentials(page)

            # 📸 إرسال Screenshot بعد الاستخراج
            shot = await take_screenshot(page, "credentials")
            if shot:
                await send_photo(
                    msg, shot,
                    f"📸 credentials\n👤 `{email}`\n🔑 {'✅' if password else '❌'}"
                )

            context.bot_data[f"page_{user_id}"] = page
            context.bot_data[f"browser_{user_id}"] = browser
            context.bot_data[f"ctx_{user_id}"] = ctx

            await db.set_session(
                user_id=user_id,
                username=email,
                password=password,
                state="waiting_password" if not password else "ready_to_login"
            )

            if password:
                # ✅ عندنا email + password → نكملو مباشرة
                await msg.edit_text(
                    f"✅ *#{job_id}*\n\n"
                    f"👤 `{email}`\n"
                    f"🔑 كلمة السر مستخرجة\n\n"
                    f"🚀 جاري تسجيل الدخول والنشر...",
                    parse_mode=ParseMode.MARKDOWN,
                )
                asyncio.create_task(run_step2_login(
                    job_id, email, password, msg, user.id, context
                ))
            else:
                # ❌ ماعندناش password → نسألو
                await msg.edit_text(
                    f"✅ *#{job_id}*\n\n"
                    f"👤 `{email}`\n\n"
                    f"🔑 *الرابط ما فيهش كلمة السر*\n"
                    f"أرسل كلمة السر الآن:",
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


# ==================== استقبال password ====================

async def handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip()

    session = await db.get_session(user.id)
    if not session or session.get("state") != "waiting_password":
        return

    job_id = session["job_id"]
    email = session["username"]

    try:
        await update.message.delete()
    except Exception:
        pass

    await db.set_session(
        user_id=user.id, password=text, state="ready_to_login"
    )

    msg = await update.message.reply_text(
        f"✅ تم استلام كلمة السر\n\n🚀 جاري تسجيل الدخول والنشر...",
        parse_mode=ParseMode.MARKDOWN,
    )

    asyncio.create_task(run_step2_login(
        job_id, email, text, msg, user.id, context
    ))


# ==================== Step 2: النشر ====================

async def run_step2_login(job_id, username, password, msg, user_id, context):
    async with job_lock:
        try:
            page = context.bot_data.get(f"page_{user_id}")
            if not page:
                raise RuntimeError("الجلسة انتهت. أرسل SSO من جديد.")

            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n🔹 تسجيل الدخول...",
                parse_mode=ParseMode.MARKDOWN,
            )
            cc = CloudConsole(page.context)
            console_page = await cc.login(username, password)

            # 📸 إرسال Screenshot بعد تسجيل الدخول
            shot = await take_screenshot(console_page, "after_login")
            if shot:
                await send_photo(msg, shot, "📸 بعد تسجيل الدخول")

            await asyncio.sleep(5)

            # 🔧 محاولة استخراج project_id (متعدد الطرق)
            project_id = await get_project_id(console_page, username)
            if not project_id:
                # 📸 إرسال Screenshot الفشل
                shot = await take_screenshot(console_page, "no_project")
                if shot:
                    await send_photo(msg, shot, "❌ تعذر استخراج project_id")

                # 🔧 محاولة أخيرة: نروحو لصفحة Home
                try:
                    await console_page.goto(
                        "https://console.cloud.google.com/home/dashboard",
                        wait_until="domcontentloaded",
                    )
                    await asyncio.sleep(6)
                    shot2 = await take_screenshot(console_page, "home_dashboard")
                    if shot2:
                        await send_photo(msg, shot2, "📸 Home Dashboard")

                    project_id = await get_project_id(console_page, username)
                    if not project_id:
                        raise RuntimeError(
                            f"تعذر استخراج project_id\n"
                            f"URL: {console_page.url[:200]}"
                        )
                except Exception as e2:
                    raise RuntimeError(
                        f"تعذر استخراج project_id\n"
                        f"URL: {console_page.url[:200]}\n"
                        f"الخطأ: {str(e2)[:150]}"
                    )

            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n"
                f"📦 `{project_id}`\n"
                f"🔹 استخراج access token...",
                parse_mode=ParseMode.MARKDOWN,
            )

            from automation.cloudrun_deployer import CloudRunDeployer, extract_access_token
            token = await extract_access_token(console_page)

            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n"
                f"🔹 نشر `{SERVICE_NAME}`...\n"
                f"🐳 `{IMAGE}`\n"
                f"🌍 {REGION} | 💾 {MEMORY} | ⚙️ {CPU}\n"
                f"⏳ 1-3 دقائق",
                parse_mode=ParseMode.MARKDOWN,
            )

            deployer = CloudRunDeployer(
                access_token=token,
                project_id=project_id,
                region=REGION,
            )
            url = await deployer.deploy(
                service_name=SERVICE_NAME,
                image=IMAGE,
                memory=MEMORY,
                cpu=CPU,
                port=PORT,
                allow_unauthenticated=True,
            )

            # 📸 Screenshot بعد النشر
            try:
                await console_page.goto(
                    f"https://console.cloud.google.com/run/detail/"
                    f"{REGION}/{SERVICE_NAME}?project={project_id}",
                    wait_until="domcontentloaded",
                )
                await asyncio.sleep(5)
                shot = await take_screenshot(console_page, "deployed")
                if shot:
                    await send_photo(msg, shot, "📸 Cloud Run بعد النشر")
            except Exception:
                pass

            await db.update_job(job_id, "done", url)
            await db.clear_session(user_id)

            await msg.edit_text(
                f"✅ *#{job_id}* — تم النشر!\n\n"
                f"🔗 *الرابط:*\n{url}\n\n"
                f"📦 `{SERVICE_NAME}`\n"
                f"🌍 `{REGION}`",
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
            try:
                pg = context.bot_data.pop(f"page_{user_id}", None)
                if pg:
                    try:
                        await pg.close()
                    except Exception:
                        pass
            except Exception:
                pass
            b = context.bot_data.pop(f"browser_{user_id}", None)
            context.bot_data.pop(f"ctx_{user_id}", None)
            if b:
                try:
                    await b.close()
                except Exception:
                    pass


# ==================== project_id (محسن) ====================

async def get_project_id(page, username: str = None) -> str:
    """يستخرج project_id بـ 5 طرق"""
    import re

    # طريقة 1: من URL
    url = page.url
    m = re.search(r'project=([a-z0-9\-]+)', url)
    if m:
        return m.group(1)

    # طريقة 2: من Cloud Resource Manager API
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

    # طريقة 3: من اسم الـ Lab (qwiklabs-gcp-XX-XXXXX)
    if username:
        m = re.search(r'qwiklabs', username.lower())
        # username format: student-XX-XXXXX@qwiklabs.net
        # project format: qwiklabs-gcp-XX-XXXXXX

    # طريقة 4: من localStorage
    try:
        pid = await page.evaluate("""
            () => {
                const el = document.querySelector('[data-project-id]');
                if (el) return el.getAttribute('data-project-id');

                for (let i = 0; i < localStorage.length; i++) {
                    const k = localStorage.key(i);
                    if (k && (k.includes('project') || k.includes('Project'))) {
                        const v = localStorage.getItem(k);
                        const m = v && v.match(/qwiklabs-gcp-[a-z0-9\-]+/);
                        if (m) return m[0];
                    }
                }

                // من الـ title
                const title = document.title;
                const m = title.match(/qwiklabs-gcp-[a-z0-9\-]+/);
                if (m) return m[0];

                return null;
            }
        """)
        if pid:
            log.info(f"✅ project_id من localStorage: {pid}")
            return pid
    except Exception as e:
        log.warning(f"فشل localStorage: {e}")

    # طريقة 5: من Cloud Console API (v3)
    try:
        pid = await page.evaluate("""
            async () => {
                try {
                    const res = await fetch(
                        'https://cloudconsole-pa.clients6.google.com/v3/entities:list?parentId=',
                        { credentials: 'include' }
                    );
                    const text = await res.text();
                    const m = text.match(/qwiklabs-gcp-[a-z0-9\-]+/);
                    if (m) return m[0];
                } catch(e) {}
                return null;
            }
        """)
        if pid:
            log.info(f"✅ project_id من Console API: {pid}")
            return pid
    except Exception:
        pass

    # طريقة 6: من أي fetch للـ API
    try:
        pid = await page.evaluate("""
            async () => {
                try {
                    const res = await fetch(
                        'https://console.cloud.google.com/apis/credentials',
                        { credentials: 'include' }
                    );
                    const text = await res.text();
                    const m = text.match(/qwiklabs-gcp-[a-z0-9\-]+/);
                    if (m) return m[0];
                } catch(e) {}
                return null;
            }
        """)
        if pid:
            log.info(f"✅ project_id من credentials API: {pid}")
            return pid
    except Exception:
        pass

    return None


# ==================== الأزرار ====================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "status":
        await status_cmd(update, context)
    elif query.data == "help":
        await query.message.reply_text(messages.WELCOME, parse_mode=ParseMode.MARKDOWN)
