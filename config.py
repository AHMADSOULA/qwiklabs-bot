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

    # ===== Proxy =====
    PROXY_ENABLED = os.getenv("PROXY_ENABLED", "false").lower() == "true"
    PROXY_SERVER = os.getenv("PROXY_SERVER", "")
    PROXY_USERNAME = os.getenv("PROXY_USERNAME", "")
    PROXY_PASSWORD = os.getenv("PROXY_PASSWORD", "")

    # ===== CAPTCHA =====
    CAPTCHA_MODE = os.getenv("CAPTCHA_MODE", "manual")  # manual | truecaptcha
    CAPTCHA_USERID = os.getenv("CAPTCHA_USERID", "")
    CAPTCHA_APIKEY = os.getenv("CAPTCHA_APIKEY", "")

    # ===== Deploy Config =====
    DEFAULT_IMAGE = os.getenv("DEFAULT_IMAGE", "docker.io/ajndjd2/ahmed-vip1")
    DEFAULT_SERVICE = os.getenv("DEFAULT_SERVICE", "ahmed-vip1")
    DEFAULT_REGION = os.getenv("DEFAULT_REGION", "us-central1")
    DEFAULT_MEMORY = os.getenv("DEFAULT_MEMORY", "2Gi")
    DEFAULT_CPU = os.getenv("DEFAULT_CPU", "2")
    DEFAULT_PORT = int(os.getenv("DEFAULT_PORT", "8080"))


config = Config()
