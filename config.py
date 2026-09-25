import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ===== Telegram =====
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

    # ===== Database =====
    DB_PATH = os.getenv("DB_PATH", "./data/bot.db")
    LOG_DIR = "./logs"

    # ===== Playwright =====
    HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
    CHROME_PROFILE_DIR = os.getenv("CHROME_PROFILE_DIR", "./data/chrome_profile")
    PAGE_TIMEOUT = int(os.getenv("PAGE_TIMEOUT", "60")) * 1000
    NAV_TIMEOUT = int(os.getenv("NAV_TIMEOUT", "90")) * 1000

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )

    # ===== Proxy (معطل) =====
    PROXY_ENABLED = False
    PROXY_SERVER = ""
    PROXY_USERNAME = ""
    PROXY_PASSWORD = ""

    # ===== TrueCaptcha =====
    CAPTCHA_USERID = os.getenv("CAPTCHA_USERID", "")
    CAPTCHA_APIKEY = os.getenv("CAPTCHA_APIKEY", "")


config = Config()
