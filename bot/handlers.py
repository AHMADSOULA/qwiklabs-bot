import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from bot import messages
from bot.keyboards import main_menu
from database import db
from utils.helpers import extract_urls
from utils.logger import get_logger
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


async def run_job(job_id, sso_url, msg):
    async with job_lock:
        browser = StealthBrowser()
        try:
            await msg.edit_text(f"🚀 *#{job_id}*\n\n🔹 إطلاق المتصفح...", parse_mode=ParseMode.MARKDOWN)
            ctx = await browser.start()
            ql = QwikLabsSession(ctx)
            page = await ql.open_sso(sso_url)
            await msg.edit_text(f"🚀 *#{job_id}*\n\n🔹 استخراج البيانات...", parse_mode=ParseMode.MARKDOWN)
            username, password = await ql.extract_credentials(page)
            await msg.edit_text(f"🚀 *#{job_id}*\n\n🔹 تسجيل الدخول...", parse_mode=ParseMode.MARKDOWN)
            cc = CloudConsole(ctx)
            console_page = await cc.login(username, password)
            await db.update_job(job_id, "done", f"logged_in:{username}")
            await msg.edit_text(
                f"✅ *#{job_id}*\n\n👤 `{username}`\n\n🔗 {console_page.url}",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            log.exception("فشل تنفيذ المهمة")
            await db.update_job(job_id, "failed", str(e))
            await msg.edit_text(
                messages.FAILED.format(error=str(e)[:300]), parse_mode=ParseMode.MARKDOWN
            )
        finally:
            await browser.close()


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "status":
        await status_cmd(update, context)
    elif query.data == "help":
        await query.message.reply_text(messages.WELCOME, parse_mode=ParseMode.MARKDOWN)
