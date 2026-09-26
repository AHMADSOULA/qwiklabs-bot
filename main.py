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
    await init_db()
    log.info("✅ DB ready")


def main():
    log.info("🚀 starting...")
    app = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", handlers.start))
    app.add_handler(CommandHandler("help", handlers.help_cmd))
    app.add_handler(CommandHandler("status", handlers.status_cmd))
    app.add_handler(CommandHandler("cancel", handlers.cancel_cmd))
    app.add_handler(CallbackQueryHandler(handlers.button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_url))
    log.info("✅ running")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
