from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters,
)

from config import config
from bot import handlers
from database.db import init_db
from utils.logger import get_logger

log = get_logger("Main")


async def post_init(app):
    """يتم تنفيذها بعد تهيئة التطبيق — قبل ما يبدأ polling"""
    await init_db()
    log.info("✅ تم تهيئة قاعدة البيانات")


async def route_text(update, context):
    """
    يوجه الرسائل حسب الحالة:
    - إذا فيها URL → SSO
    - إذا CAPTCHA في انتظار → حل CAPTCHA
    - إذا الحالة waiting_password → password
    """
    from database import db
    from utils.helpers import extract_urls

    # ✅ محاولة استيراد CAPTCHA (اختياري)
    try:
        from automation.captcha_solver import set_captcha_solution, PENDING_CAPTCHA
        has_captcha = True
    except Exception:
        has_captcha = False
        PENDING_CAPTCHA = {}

    user = update.effective_user
    text = update.message.text or ""

    # ✅ 1. إذا CAPTCHA في انتظار
    if has_captcha and user.id in PENDING_CAPTCHA and PENDING_CAPTCHA[user.id].get("waiting"):
        set_captcha_solution(user.id, text)
        await update.message.reply_text(
            f"✅ تم استلام الحل: `{text}`",
            parse_mode="Markdown",
        )
        return

    # ✅ 2. إذا فيها URL → SSO
    if extract_urls(text):
        await handlers.handle_url(update, context)
        return

    # ✅ 3. إذا الحالة waiting_password → password
    session = await db.get_session(user.id)
    if session and session.get("state") == "waiting_password":
        await handlers.handle_password(update, context)


def main():
    log.info("🚀 بدء تشغيل البوت...")

    app = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()

    # ✅ Handlers
    app.add_handler(CommandHandler("start", handlers.start))
    app.add_handler(CommandHandler("help", handlers.help_cmd))
    app.add_handler(CommandHandler("status", handlers.status_cmd))
    app.add_handler(CommandHandler("cancel", handlers.cancel_cmd))
    app.add_handler(CallbackQueryHandler(handlers.button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, route_text))

    log.info("✅ البوت يعمل الآن.")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
