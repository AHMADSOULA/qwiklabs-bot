from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu():
    keyboard = [
        [InlineKeyboardButton("📊 حالتي", callback_data="status")],
        [InlineKeyboardButton("❓ مساعدة", callback_data="help")],
    ]
    return InlineKeyboardMarkup(keyboard)


def region_menu():
    keyboard = [
        [InlineKeyboardButton("🇺🇸 US Central (أرخص)", callback_data="region:us-central1")],
        [InlineKeyboardButton("🇺🇸 US East", callback_data="region:us-east1")],
        [InlineKeyboardButton("🇺🇸 US West", callback_data="region:us-west1")],
        [InlineKeyboardButton("🇪🇺 Europe West", callback_data="region:europe-west1")],
        [InlineKeyboardButton("🇪🇺 Europe Central", callback_data="region:europe-central2")],
        [InlineKeyboardButton("🇸🇬 Asia Southeast", callback_data="region:asia-southeast1")],
        [InlineKeyboardButton("🇯🇵 Asia Northeast", callback_data="region:asia-northeast1")],
        [InlineKeyboardButton("🌍 اختر تلقائي", callback_data="region:auto")],
    ]
    return InlineKeyboardMarkup(keyboard)


def memory_menu():
    keyboard = [
        [
            InlineKeyboardButton("512 MiB", callback_data="mem:512Mi"),
            InlineKeyboardButton("1 GiB", callback_data="mem:1Gi"),
        ],
        [
            InlineKeyboardButton("2 GiB", callback_data="mem:2Gi"),
            InlineKeyboardButton("4 GiB", callback_data="mem:4Gi"),
        ],
        [
            InlineKeyboardButton("8 GiB", callback_data="mem:8Gi"),
            InlineKeyboardButton("16 GiB", callback_data="mem:16Gi"),
        ],
        [InlineKeyboardButton("🌍 اختر تلقائي (1Gi)", callback_data="mem:auto")],
    ]
    return InlineKeyboardMarkup(keyboard)


def cpu_menu():
    keyboard = [
        [
            InlineKeyboardButton("1 vCPU", callback_data="cpu:1"),
            InlineKeyboardButton("2 vCPU", callback_data="cpu:2"),
        ],
        [
            InlineKeyboardButton("4 vCPU", callback_data="cpu:4"),
            InlineKeyboardButton("8 vCPU", callback_data="cpu:8"),
        ],
        [InlineKeyboardButton("🌍 اختر تلقائي (1)", callback_data="cpu:auto")],
    ]
    return InlineKeyboardMarkup(keyboard)


def confirm_menu():
    keyboard = [
        [
            InlineKeyboardButton("✅ تأكيد النشر", callback_data="confirm:yes"),
            InlineKeyboardButton("❌ إلغاء", callback_data="confirm:no"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)
