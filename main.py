import asyncio
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters,
)

from config import config
from bot import handlers
from database.db import init_db
from utils.logger import get_logger

log = get_logger("Main")


async def main():
    log.info("🚀 بدء تشغيل البوت...")
    await init_db()
    log.info("✅ تم تهيئة قاعدة البيانات")
    app = Application.builder().token(config.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", handlers.start))
    app.add_handler(CommandHandler("help", handlers.help_cmd))
    app.add_handler(CommandHandler("status", handlers.status_cmd))
    app.add_handler(CommandHandler("cancel", handlers.cancel_cmd))
    app.add_handler(CallbackQueryHandler(handlers.button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_url))
    log.info("✅ البوت يعمل الآن.")
    await app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("تم الإيقاف")
