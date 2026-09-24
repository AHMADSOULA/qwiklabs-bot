import os
import json
from playwright.async_api import async_playwright
from config import config
from automation.stealth import STEALTH_JS
from utils.logger import get_logger

log = get_logger("Browser")


class StealthBrowser:
    def __init__(self):
        self.playwright = None
        self.context = None

    async def start(self):
        self.playwright = await async_playwright().start()

        # ✅ المسار المثبت (فـ Volume)
        profile_dir = config.CHROME_PROFILE_DIR
        os.makedirs(profile_dir, exist_ok=True)

        # ✅ فحص واش الجلسة موجودة من قبل
        session_exists = os.path.exists(
            os.path.join(profile_dir, "Default", "Cookies")
        )
        if session_exists:
            log.info("✅ وجدت Chrome Profile محفوظ — غادي نستعملو")
        else:
            log.info("🆕 Chrome Profile جديد — أول مرة")

        args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-setuid-sandbox",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-infobars",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--window-size=1920,1080",
            f"--user-agent={config.USER_AGENT}",
        ]

        proxy = None
        if config.PROXY_ENABLED and config.PROXY_SERVER:
            proxy = {
                "server": config.PROXY_SERVER,
                "username": config.PROXY_USERNAME,
                "password": config.PROXY_PASSWORD,
            }

        launch_kwargs = {
            "user_data_dir": profile_dir,
            "headless": config.HEADLESS,
            "args": args,
            "viewport": {"width": 1920, "height": 1080},
            "user_agent": config.USER_AGENT,
            "locale": "en-US",
            "timezone_id": "America/New_York",
            "color_scheme": "light",
            "device_scale_factor": 1,
            "is_mobile": False,
            "has_touch": False,
            "java_script_enabled": True,
            "extra_http_headers": {
                "Accept-Language": "en-US,en;q=0.9",
                "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            },
        }
        if proxy:
            launch_kwargs["proxy"] = proxy

        # نحاول Chrome الحقيقي أولاً
        try:
            launch_kwargs["channel"] = "chrome"
            self.context = await self.playwright.chromium.launch_persistent_context(**launch_kwargs)
        except Exception as e:
            log.warning(f"فشل Chrome channel: {e}")
            launch_kwargs.pop("channel", None)
            self.context = await self.playwright.chromium.launch_persistent_context(**launch_kwargs)

        # ✅ نضيف الـ STEALTH
        await self.context.add_init_script(STEALTH_JS)

        # ✅ منع الكشف من خلال الـ navigator
        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        self.context.set_default_timeout(config.PAGE_TIMEOUT)
        self.context.set_default_navigation_timeout(config.NAV_TIMEOUT)

        log.info("✅ تم إطلاق المتصفح المخفي بنجاح")
        return self.context

    async def close(self):
        if self.context:
            # ✅ نحفظ الـ cookies قبل الإغلاق
            try:
                cookies = await self.context.cookies()
                profile_dir = config.CHROME_PROFILE_DIR
                cookies_file = os.path.join(profile_dir, "cookies_backup.json")
                with open(cookies_file, "w") as f:
                    json.dump(cookies, f)
                log.info(f"✅ تم حفظ {len(cookies)} cookies")
            except Exception as e:
                log.warning(f"فشل حفظ cookies: {e}")

            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
        log.info("تم إغلاق المتصفح")
