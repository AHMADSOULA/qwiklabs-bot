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
from utils.diagnostic import (
    start_report, get_report, send_diagnostic, get_system_info,
)
from automation.browser import StealthBrowser
from automation.qwiklabs import QwikLabsSession
from automation.cloud_console import CloudConsole

log = get_logger("Handlers")
job_lock = asyncio.Lock()

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
    if not jobs:
        await update.message.reply_text("📭 لا توجد مهام.")
        return
    lines = []
    for jid, status, created in jobs:
        emoji = {"pending": "⏳", "done": "✅", "failed": "❌", "waiting_password": "🔑"}.get(status, "❔")
        lines.append(messages.JOB_LINE.format(id=jid, status_emoji=emoji, status=status, date=created))
    await update.message.reply_text(
        messages.STATUS_TEMPLATE.format(count=len(jobs), jobs="\n".join(lines)),
        parse_mode=ParseMode.MARKDOWN,
    )


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
    except Exception as e:
        log.warning(f"فشل صورة: {e}")


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    urls = extract_urls(text)
    if not urls:
        await update.message.reply_text(messages.NO_URL)
        return
    sso_url = urls[0]
    user = update.effective_user
    if "skills.google" not in sso_url and "qwiklabs" not in sso_url and "AddSession" not in sso_url:
        await update.message.reply_text("⚠️ الرابط ماشي من Google Skills.")
        return

    existing = await db.get_session(user.id)
    if existing:
        await update.message.reply_text("⚠️ عندك مهمة. أرسل `/cancel`.", parse_mode=ParseMode.MARKDOWN)
        return

    job_id = await db.add_job(user.id, sso_url)
    await db.set_session(user_id=user.id, job_id=job_id, sso_url=sso_url, state="opening_sso")

    report = start_report(job_id, user.id)
    report.add_step("استلام SSO", "✅", sso_url[:100])
    for k, v in get_system_info().items():
        report.set_metadata(k, v)

    msg = await update.message.reply_text(
        f"📥 المهمة `#{job_id}`\n\n🔹 جاري التحقق من الرابط...",
        parse_mode=ParseMode.MARKDOWN,
    )
    asyncio.create_task(run_step1(job_id, sso_url, msg, user.id, context))


async def run_step1(job_id, sso_url, msg, user_id, context):
    async with job_lock:
        browser = StealthBrowser()
        report = get_report(job_id)
        try:
            # ✅ 1. إطلاق المتصفح
            await msg.edit_text(f"🚀 *#{job_id}*\n\n🔹 إطلاق المتصفح...", parse_mode=ParseMode.MARKDOWN)
            report.add_step("إطلاق المتصفح", "ℹ️", "بدء")
            ctx = await browser.start()
            report.add_step("إطلاق المتصفح", "✅", "نجح")

            # ✅ 2. فتح SSO
            await msg.edit_text(f"🚀 *#{job_id}*\n\n🔹 فتح SSO...", parse_mode=ParseMode.MARKDOWN)
            ql = QwikLabsSession(ctx)
            page = await ql.open_sso(sso_url)

            shot = await take_screenshot(page, "sso")
            if shot:
                report.add_screenshot(shot, "بعد SSO")
                await send_photo(msg, shot, "📸 بعد فتح SSO")

            # ✅ 3. التحقق من SSO
            is_valid, reason = await ql.check_sso_valid(page)
            report.add_step("التحقق من SSO", "✅" if is_valid else "❌", reason)

            if not is_valid:
                await msg.edit_text(f"❌ *#{job_id}* — فشل\n\n📋 {reason}", parse_mode=ParseMode.MARKDOWN)
                await db.update_job(job_id, "failed", reason)
                await db.clear_session(user_id)
                await browser.close()
                return

            # ✅ 4. استخراج credentials
            await msg.edit_text(f"🚀 *#{job_id}*\n\n🔹 استخراج البيانات...", parse_mode=ParseMode.MARKDOWN)
            email, password = await ql.extract_credentials(page)
            report.add_step("استخراج credentials", "✅", f"email: {email}, pass: {'✅' if password else '❌'}")

            shot = await take_screenshot(page, "credentials")
            if shot:
                report.add_screenshot(shot, f"credentials: {email}")
                await send_photo(msg, shot, f"📸\n👤 `{email}`")

            context.bot_data[f"page_{user_id}"] = page
            context.bot_data[f"browser_{user_id}"] = browser
            context.bot_data[f"ctx_{user_id}"] = ctx

            await db.set_session(
                user_id=user_id, username=email, password=password,
                state="waiting_password" if not password else "ready"
            )

            if password:
                await msg.edit_text(
                    f"✅ *#{job_id}*\n\n👤 `{email}`\n🔑 password موجود\n🚀 تسجيل الدخول...",
                    parse_mode=ParseMode.MARKDOWN,
                )
                asyncio.create_task(run_step2(job_id, email, password, msg, user.id, context))
            else:
                await msg.edit_text(
                    f"✅ *#{job_id}*\n\n👤 `{email}`\n\n🔑 *أرسل كلمة السر:*",
                    parse_mode=ParseMode.MARKDOWN,
                )
        except Exception as e:
            log.exception("SSO فشل")
            if report:
                report.add_error(e, "SSO")
            await db.update_job(job_id, "failed", str(e))
            await db.clear_session(user_id)
            await msg.edit_text(f"❌ *#{job_id}* — فشل\n\n📋 {str(e)[:300]}", parse_mode=ParseMode.MARKDOWN)
            await send_diagnostic(msg, job_id, str(e))
            try:
                await browser.close()
            except Exception:
                pass


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

    msg = await update.message.reply_text(
        f"✅ استلمنا password\n\n🚀 تسجيل الدخول...",
        parse_mode=ParseMode.MARKDOWN,
    )
    asyncio.create_task(run_step2(job_id, email, text, msg, user.id, context))


async def run_step2(job_id, username, password, msg, user_id, context):
    async with job_lock:
        report = get_report(job_id)
        try:
            page = context.bot_data.get(f"page_{user_id}")
            if not page:
                raise RuntimeError("الجلسة انتهت")

            # ✅ تسجيل الدخول (بلا user_id/sender)
            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n🔹 تسجيل الدخول...",
                parse_mode=ParseMode.MARKDOWN,
            )
            report.add_step("تسجيل الدخول", "ℹ️", "بدء")

            cc = CloudConsole(page.context)
            console_page = await cc.login(username, password)

            report.add_step("تسجيل الدخول", "✅", f"URL: {console_page.url[:150]}")

            # ✅ ننتظر 10 ثواني + Screenshot
            await msg.edit_text(
                f"✅ *#{job_id}*\n\n🔑 تم تسجيل الدخول\n⏳ ننتظر 10 ثواني...",
                parse_mode=ParseMode.MARKDOWN,
            )
            await asyncio.sleep(10)

            current_url = console_page.url
            log.info(f"URL بعد 10s: {current_url}")

            # ✅ Screenshot
            shot = await take_screenshot(console_page, "after_login")
            if shot:
                report.add_screenshot(shot, "بعد تسجيل الدخول")
                await send_photo(
                    msg, shot,
                    f"📸 *بعد تسجيل الدخول*\n🔗 `{current_url[:150]}`"
                )

            # ✅ نأكدو
            await msg.edit_text(
                f"✅ *#{job_id}* — دخل Google Cloud!\n\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"🔗 *URL:*\n`{current_url[:200]}`\n"
                f"👤 `{username}`\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"📸 تحقق من الصورة",
                parse_mode=ParseMode.MARKDOWN,
            )

            await db.update_job(job_id, "done", f"logged_in:{username}")
            await db.clear_session(user_id)

            log.info("✅ تم — البوت وقف")

        except Exception as e:
            log.exception("فشل تسجيل الدخول")
            if report:
                report.add_error(e, "تسجيل دخول")
            await db.update_job(job_id, "failed", str(e))
            await db.clear_session(user_id)
            await msg.edit_text(
                f"❌ *#{job_id}* — فشل\n\n📋 {str(e)[:300]}",
                parse_mode=ParseMode.MARKDOWN,
            )
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
