import asyncio
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
        emoji = {"pending": "⏳", "done": "✅", "failed": "❌"}.get(status, "❔")
        lines.append(messages.JOB_LINE.format(
            id=jid, status_emoji=emoji, status=status, date=created
        ))
    await update.message.reply_text(
        messages.STATUS_TEMPLATE.format(count=len(jobs), jobs="\n".join(lines)),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 تم الإلغاء.")


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
    job_id = await db.add_job(user.id, sso_url)
    msg = await update.message.reply_text(
        f"📥 تم استلام المهمة `#{job_id}`\n\n{messages.PROCESSING}",
        parse_mode=ParseMode.MARKDOWN,
    )
    asyncio.create_task(run_job(job_id, sso_url, msg))


async def send_photo(msg, filepath, caption=""):
    """يرسل صورة فـ تليجرام"""
    try:
        if not filepath:
            return
        with open(filepath, "rb") as f:
            await msg.reply_photo(photo=InputFile(f), caption=caption[:1000])
    except Exception as e:
        log.error(f"فشل إرسال الصورة: {e}")


async def run_job(job_id, sso_url, msg):
    async with job_lock:
        browser = StealthBrowser()
        try:
            # 1. إطلاق المتصفح
            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n🔹 إطلاق المتصفح المخفي...",
                parse_mode=ParseMode.MARKDOWN,
            )
            ctx = await browser.start()

            # 2. فتح SSO
            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n🔹 فتح رابط SSO...",
                parse_mode=ParseMode.MARKDOWN,
            )
            ql = QwikLabsSession(ctx)
            page = await ql.open_sso(sso_url)

            shot = await take_screenshot(page, "01_after_sso")
            if shot:
                await send_photo(msg, shot, "📸 1. بعد فتح SSO")

            # 3. استخراج credentials
            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n🔹 استخراج credentials...",
                parse_mode=ParseMode.MARKDOWN,
            )
            try:
                username, password = await ql.extract_credentials(page)
            except Exception as e:
                shot = await take_screenshot(page, "02_error_extract")
                if shot:
                    await send_photo(msg, shot, f"❌ فشل استخراج\n{str(e)[:300]}")
                raise

            shot = await take_screenshot(page, "03_credentials_ok")
            if shot:
                await send_photo(msg, shot, f"📸 2. credentials\n👤 {username}")

            # 4. تسجيل الدخول
            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n🔹 تسجيل الدخول لـ Cloud Console...",
                parse_mode=ParseMode.MARKDOWN,
            )
            cc = CloudConsole(ctx)
            console_page = await cc.login(username, password)

            shot = await take_screenshot(console_page, "04_console_login")
            if shot:
                await send_photo(msg, shot, "📸 3. بعد تسجيل الدخول")

            # 5. Project ID
            project_id = await get_project_id(console_page)
            if not project_id:
                shot = await take_screenshot(console_page, "05_no_project")
                if shot:
                    await send_photo(msg, shot, "❌ تعذر استخراج project ID")
                raise RuntimeError("تعذر استخراج project ID من URL")

            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n"
                f"🔹 استخراج access token...\n"
                f"📦 `{project_id}`",
                parse_mode=ParseMode.MARKDOWN,
            )

            # 6. Token
            from automation.cloudrun_deployer import CloudRunDeployer, extract_access_token
            try:
                token = await extract_access_token(console_page)
            except Exception as e:
                shot = await take_screenshot(console_page, "06_token_error")
                if shot:
                    await send_photo(msg, shot, f"❌ فشل التوكن\n{str(e)[:300]}")
                raise

            shot = await take_screenshot(console_page, "07_token_ok")
            if shot:
                await send_photo(msg, shot, "📸 4. تم استخراج التوكن")

            # 7. النشر
            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n"
                f"🔹 نشر `ahmed-vip1`...\n"
                f"⏳ 1-3 دقائق\n"
                f"📦 `{project_id}`",
                parse_mode=ParseMode.MARKDOWN,
            )

            deployer = CloudRunDeployer(
                access_token=token,
                project_id=project_id,
                region="us-central1",
            )

            try:
                url = await deployer.deploy(
                    service_name="ahmed-vip1",
                    image="docker.io/ajndjd2/ahmed-vip1",
                    memory="4Gi",
                    cpu="2",
                    port=8080,
                    allow_unauthenticated=True,
                )
            except Exception as e:
                shot = await take_screenshot(console_page, "08_deploy_error")
                if shot:
                    await send_photo(msg, shot, f"❌ فشل النشر\n{str(e)[:300]}")
                raise

            # 8. Screenshot النهائي
            try:
                await console_page.goto(
                    f"https://console.cloud.google.com/run/detail/"
                    f"{deployer.region}/ahmed-vip1?project={project_id}",
                    wait_until="domcontentloaded",
                )
                await asyncio.sleep(5)
                shot = await take_screenshot(console_page, "09_deployed")
                if shot:
                    await send_photo(msg, shot, "📸 5. Cloud Run بعد النشر")
            except Exception:
                pass

            await db.update_job(job_id, "done", url)
            await msg.edit_text(
                f"✅ *#{job_id}* — تم النشر بنجاح!\n\n"
                f"🔗 *الرابط:*\n{url}\n\n"
                f"👤 `{username}`\n"
                f"📦 `{project_id}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            log.exception("فشل تنفيذ المهمة")
            await db.update_job(job_id, "failed", str(e))
            await msg.edit_text(
                messages.FAILED.format(error=str(e)[:300]),
                parse_mode=ParseMode.MARKDOWN,
            )
        finally:
            await browser.close()


async def get_project_id(page) -> str:
    """يستخرج project ID من URL ديال Cloud Console"""
    import re
    url = page.url
    m = re.search(r'project=([a-z0-9\-]+)', url)
    if m:
        return m.group(1)
    try:
        pid = await page.evaluate("""
            () => {
                if (window._gcp_project) return window._gcp_project;
                const el = document.querySelector('[data-project-id]');
                if (el) return el.getAttribute('data-project-id');
                return null;
            }
        """)
        return pid
    except Exception:
        return None


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "status":
        await status_cmd(update, context)
    elif query.data == "help":
        await query.message.reply_text(messages.WELCOME, parse_mode=ParseMode.MARKDOWN)
