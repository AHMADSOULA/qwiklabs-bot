from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 حالتي", callback_data="status")],
        [InlineKeyboardButton("❓ مساعدة", callback_data="help")],
    ])
