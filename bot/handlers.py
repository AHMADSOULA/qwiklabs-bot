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
from utils.queue_manager import queue_manager
from utils.diagnostic import (
    start_report, get_report, send_diagnostic, get_system_info,
)
from automation.browser import StealthBrowser
from automation.qwiklabs import QwikLabsSession
from automation.cloud_console import CloudConsole

log = get_logger("Handlers")

# ⚙️ إعدادات
IMAGE = "docker.io/ajndjd2/ahmed-vip1"
SERVICE = "ahmed-vip1"
REGION = "us-central1"
MEMORY = "2Gi"
CPU = "2"
PORT = 8080


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
    queue_size = queue_manager.queue_size()
    busy = "🔴 مشغول" if queue_manager.is_busy() else "🟢 متاح"

    lines = [f"📊 *حالة الطابور:*", f"• {busy}", f"• 📋 في الانتظار: {queue_size}", ""]
    if jobs:
        lines.append("*آخر مهام:*")
        for jid, status, created in jobs:
            emoji = {"pending": "⏳", "done": "✅", "failed": "❌", "waiting_password": "🔑"}.get(status, "❔")
            lines.append(messages.JOB_LINE.format(id=jid, status_emoji=emoji, status=status, date=created))
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        from automation.captcha_solver import cancel_captcha
        cancel_captcha(user.id)
    except Exception:
        pass
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


async def send_photo(msg, path, caption=""):
    try:
        if not path:
            return
        import os
        if not os.path.exists(path):
            return
        with open(path, "rb") as f:
            await msg.reply_photo(photo=InputFile(f), caption=caption[:1000])
    except Exception:
        pass


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    urls = extract_urls(text)
    if not urls:
        await update.message.reply_text(messages.NO_URL)
        return
    sso_url = urls[0]
    user = update.effective_user
    if "skills.google" not in sso_url and "qwiklabs" not in sso_url:
        await update.message.reply_text("⚠️ الرابط ماشي من Google Skills.")
        return

    existing = await db.get_session(user.id)
    if existing:
        await update.message.reply_text("⚠️ عندك مهمة. أرسل `/cancel`.", parse_mode=ParseMode.MARKDOWN)
        return

    job_id = await db.add_job(user.id, sso_url)
    await db.set_session(user_id=user.id, job_id=job_id, sso_url=sso_url, state="queued")

    report = start_report(job_id, user.id)
    report.add_step("استلام SSO", "✅", sso_url[:100])
    for k, v in get_system_info().items():
        report.set_metadata(k, v)

    # ✅ نضيف للطابور
    num = await queue_manager.add(user.id, job_id, sso_url, sender=update.message, context=context)

    position = queue_manager.queue_size()

    msg = await update.message.reply_text(
        f"📥 *تم استلام الرابط رقم {num}.*\n"
        f"وسيبدأ الآن.",
        parse_mode=ParseMode.MARKDOWN,
    )
    asyncio.create_task(run_job(num, job_id, sso_url, user.id, msg, context))


async def run_job(num, job_id, sso_url, user_id, msg, context):
    # ✅ ننتظر الدور
    while True:
        item = await queue_manager.get_next()
        if item and item["num"] == num:
            break
        await asyncio.sleep(2)

    browser = StealthBrowser()
    report = get_report(job_id)
    try:
        await msg.edit_text(
            f"[@{user_id}] • 1) فتح رابط الطالب..."
        )
        report.add_step("فتح رابط", "ℹ️", "بدء")

        ctx = await browser.start()
        ql = QwikLabsSession(ctx)
        page = await ql.open_sso(sso_url)

        # ✅ التحقق
        is_valid, reason = await ql.check_sso_valid(page)
        if not is_valid:
            await msg.edit_text(f"[@{user_id}] ❌ {reason}")
            await db.update_job(job_id, "failed", reason)
            await db.clear_session(user_id)
            await browser.close()
            await queue_manager.finish_current()
            return

        await msg.edit_text(f"[@{user_id}] • 2 ✅")
        report.add_step("فتح", "✅", reason)

        # ✅ استخراج
        email, password = await ql.extract_credentials(page)
        report.add_step("استخراج", "✅", f"email: {email}")

        context.bot_data[f"page_{user_id}"] = page
        context.bot_data[f"browser_{user_id}"] = browser
        context.bot_data[f"ctx_{user_id}"] = ctx

        await db.set_session(
            user_id=user_id, username=email, password=password,
            state="waiting_password" if not password else "ready"
        )

        if password:
            await msg.edit_text(f"[@{user_id}] • 3 ✅\n🚀 جاري التسجيل...")
            asyncio.create_task(run_step2(num, job_id, email, password, msg, user.id, context))
        else:
            await msg.edit_text(
                f"[@{user_id}] • 🔒 *مطلوب كلمة السر*\n\n"
                f"أرسل كلمة السر هنا."
            )
    except Exception as e:
        log.exception("فشل")
        await msg.edit_text(f"[@{user_id}] ❌ {str(e)[:200]}")
        await db.update_job(job_id, "failed", str(e))
        await db.clear_session(user_id)
        try:
            await browser.close()
        except Exception:
            pass
        await queue_manager.finish_current()


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

    await db.set_session(user_id=user.id, password=text, state="ready")

    report = get_report(job_id)
    if report:
        report.add_step("استقبال password", "✅", "من المستخدم")

    msg = await update.message.reply_text(f"✅ (password) تم الإرسال")

    # ✅ نلقاو num
    num = None
    if queue_manager.current and queue_manager.current["user_id"] == user.id:
        num = queue_manager.current["num"]

    asyncio.create_task(run_step2(num, job_id, email, text, msg, user.id, context))


async def run_step2(num, job_id, username, password, msg, user_id, context):
    report = get_report(job_id)
    try:
        page = context.bot_data.get(f"page_{user_id}")
        if not page:
            raise RuntimeError("الجلسة انتهت")

        await msg.edit_text(f"[@{user_id}] • 3 ⏳ تسجيل الدخول...")
        report.add_step("تسجيل الدخول", "ℹ️", "بدء")

        cc = CloudConsole(page.context)
        console_page = await cc.login(username, password, user_id=user_id, sender=msg)

        shot = await take_screenshot(console_page, "after_login")
        if shot:
            report.add_screenshot(shot, "بعد تسجيل الدخول")

        report.add_step("تسجيل الدخول", "✅", f"URL: {console_page.url[:150]}")
        await msg.edit_text(f"[@{user_id}] • 4 ✅ (Project: {await get_project_id(console_page, '') or 'N/A'})")
        await asyncio.sleep(2)

        # project_id
        session = await db.get_session(user_id)
        project_id = await get_project_id(console_page, session.get("sso_url", ""))
        if not project_id:
            raise RuntimeError("تعذر project_id")
        report.add_step("project_id", "✅", project_id)

        # token
        from automation.cloudrun_deployer import CloudRunDeployer, extract_access_token
        token = await extract_access_token(console_page)
        report.add_step("access token", "✅", f"طول: {len(token)}")

        # ✅ النشر
        await msg.edit_text(f"[@{user_id}] • 5 ⏳ نشر {SERVICE}...")
        report.add_step("Cloud Run deploy", "ℹ️", "بدء")

        deployer = CloudRunDeployer(token, project_id, REGION)
        url = await deployer.deploy(SERVICE, IMAGE, MEMORY, CPU, PORT)
        report.add_step("Cloud Run deploy", "✅", url)

        await db.update_job(job_id, "done", url)
        await db.clear_session(user_id)

        await msg.edit_text(
            f"[@{user_id}] • 6 ✅ *تم النشر!*\n\n"
            f"🔗 {url}"
        )
    except Exception as e:
        log.exception("نشر فشل")
        if report:
            report.add_error(e, "نشر")
        await db.update_job(job_id, "failed", str(e))
        await db.clear_session(user_id)
        await msg.edit_text(f"[@{user_id}] ❌ {str(e)[:200]}")
        await send_diagnostic(msg, job_id, str(e))
    finally:
        try:
            pg = context.bot_data.pop(f"page_{user_id}", None)
            if pg:
                await pg.close()
        except Exception:
            pass
        b = context.bot_data.pop(f"browser_{user_id}", None)
        context.bot_data.pop(f"ctx_{user_id}", None)
        if b:
            try:
                await b.close()
            except Exception:
                pass
        await queue_manager.finish_current()


async def get_project_id(page, sso_url: str = "") -> str:
    m = re.search(r'project=([a-z0-9\-]+)', page.url)
    if m:
        return m.group(1)
    if sso_url:
        m = re.search(r'project%3D([a-z0-9\-]+)', sso_url)
        if not m:
            m = re.search(r'project=([a-z0-9\-]+)', sso_url)
        if not m:
            m = re.search(r'(qwiklabs-gcp-[a-z0-9\-]+)', sso_url)
        if m:
            return m.group(1)
    try:
        pid = await page.evaluate("""
            async () => {
                try {
                    const r = await fetch('https://cloudresourcemanager.googleapis.com/v1/projects', {credentials: 'include'});
                    const d = await r.json();
                    if (d.projects && d.projects.length > 0) return d.projects[0].projectId;
                } catch(e) {}
                return null;
            }
        """)
        if pid:
            return pid
    except Exception:
        pass
    return None


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "status":
        await status_cmd(update, context)
    elif query.data == "help":
        await query.message.reply_text(messages.WELCOME, parse_mode=ParseMode.MARKDOWN)
