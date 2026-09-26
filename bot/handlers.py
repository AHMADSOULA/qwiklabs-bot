import asyncio
from telegram import Update, InputFile
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
        emoji = {"pending": "⏳", "done": "✅", "failed": "❌", "waiting_password": "🔑"}.get(status, "❔")
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


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    urls = extract_urls(text)
    if not urls:
        await update.message.reply_text(messages.NO_URL)
        return
    sso_url = urls[0]
    user = update.effective_user
    if "skills.google" not in sso_url and "qwiklabs" not in sso_url and "AddSession" not in sso_url:
        await update.message.reply_text("⚠️ الرابط لا يبدو من Google Skills.")
        return

    existing = await db.get_session(user.id)
    if existing:
        await update.message.reply_text("⚠️ عندك مهمة. أرسل `/cancel`.", parse_mode=ParseMode.MARKDOWN)
        return

    job_id = await db.add_job(user.id, sso_url)
    await db.set_session(user_id=user.id, job_id=job_id, sso_url=sso_url, state="opening_sso")

    msg = await update.message.reply_text(
        f"📥 تم استلام المهمة `#{job_id}`\n\n{messages.PROCESSING}",
        parse_mode=ParseMode.MARKDOWN,
    )
    asyncio.create_task(run_job(job_id, sso_url, msg, user.id, context))


async def run_job(job_id, sso_url, msg, user_id, context):
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

            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n🔹 استخراج البيانات...",
                parse_mode=ParseMode.MARKDOWN,
            )
            username, password = await ql.extract_credentials(page)

            # ✅ نسجلو page + browser
            context.bot_data[f"page_{user_id}"] = page
            context.bot_data[f"browser_{user_id}"] = browser
            context.bot_data[f"ctx_{user_id}"] = ctx

            # ✅ إذا password موجود → نكملو
            if password:
                await db.set_session(user_id=user_id, username=username, password=password, state="ready")
                await msg.edit_text(
                    f"✅ *#{job_id}*\n\n"
                    f"👤 `{username}`\n"
                    f"🔑 password موجود\n\n"
                    f"🚀 تسجيل الدخول...",
                    parse_mode=ParseMode.MARKDOWN,
                )
                asyncio.create_task(run_step2(job_id, username, password, msg, user.id, context))
            else:
                # ✅ نطلبو password
                await db.set_session(user_id=user_id, username=username, state="waiting_password")
                await msg.edit_text(
                    f"✅ *#{job_id}*\n\n"
                    f"👤 `{username}`\n\n"
                    f"🔑 *أرسل كلمة السر:*",
                    parse_mode=ParseMode.MARKDOWN,
                )

        except Exception as e:
            log.exception("فشل تنفيذ المهمة")
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


async def handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip()

    session = await db.get_session(user.id)
    if not session or session.get("state") != "waiting_password":
        return

    job_id = session["job_id"]
    username = session["username"]

    try:
        await update.message.delete()
    except Exception:
        pass

    await db.set_session(user_id=user.id, password=text, state="ready")

    msg = await update.message.reply_text(
        f"✅ استلمنا password\n\n🚀 تسجيل الدخول...",
        parse_mode=ParseMode.MARKDOWN,
    )
    asyncio.create_task(run_step2(job_id, username, text, msg, user.id, context))


async def run_step2(job_id, username, password, msg, user_id, context):
    async with job_lock:
        try:
            page = context.bot_data.get(f"page_{user_id}")
            if not page:
                raise RuntimeError("الجلسة انتهت. أرسل SSO جديد.")

            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n🔹 تسجيل الدخول...",
                parse_mode=ParseMode.MARKDOWN,
            )
            cc = CloudConsole(page.context)
            console_page = await cc.login(username, password)

            await db.update_job(job_id, "done", f"logged_in:{username}")
            await db.clear_session(user_id)

            await msg.edit_text(
                f"✅ *#{job_id}*\n\n"
                f"👤 `{username}`\n\n"
                f"🔗 {console_page.url}",
                parse_mode=ParseMode.MARKDOWN,
            )

        except Exception as e:
            log.exception("فشل تسجيل الدخول")
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


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "status":
        await status_cmd(update, context)
    elif query.data == "help":
        await query.message.reply_text(messages.WELCOME, parse_mode=ParseMode.MARKDOWN)
