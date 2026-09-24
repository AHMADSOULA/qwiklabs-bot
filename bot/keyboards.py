from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu():
    keyboard = [
        [InlineKeyboardButton("📊 حالتي", callback_data="status")],
        [InlineKeyboardButton("❓ مساعدة", callback_data="help")],
    ]
    return InlineKeyboardMarkup(keyboard)
