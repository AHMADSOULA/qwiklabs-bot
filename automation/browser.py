import os
from playwright.async_api import async_playwright
from config import config
from automation.stealth import STEALTH_JS
from utils.logger import get_logger

try:
    from playwright_stealth import stealth_async
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False

log = get_logger("Browser")


class StealthBrowser:
    def __init__(self):
        self.playwright = None
        self.context = None

    async def start(self):
        self.playwright = await async_playwright().start()
        os.makedirs(config.CHROME_PROFILE_DIR, exist_ok=True)

        args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-setuid-sandbox",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-infobars",
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
            "user_data_dir": config.CHROME_PROFILE_DIR,
            "headless": config.HEADLESS,
            "args": args,
            "viewport": {"width": 1920, "height": 1080},
            "user_agent": config.USER_AGENT,
            "locale": "en-US",
            "timezone_id": "America/New_York",
            "ignore_https_errors": True,
            "extra_http_headers": {
                "Accept-Language": "en-US,en;q=0.9",
            },
        }
        if proxy:
            launch_kwargs["proxy"] = proxy

        try:
            launch_kwargs["channel"] = "chrome"
            self.context = await self.playwright.chromium.launch_persistent_context(**launch_kwargs)
        except Exception as e:
            log.warning(f"Chrome channel fail: {e}")
            launch_kwargs.pop("channel", None)
            self.context = await self.playwright.chromium.launch_persistent_context(**launch_kwargs)

        await self.context.add_init_script(STEALTH_JS)

        if HAS_STEALTH:
            async def apply(page):
                try:
                    await stealth_async(page)
                except Exception:
                    pass
            self.context.on("page", apply)
            for p in self.context.pages:
                await apply(p)

        self.context.set_default_timeout(config.PAGE_TIMEOUT)
        self.context.set_default_navigation_timeout(config.NAV_TIMEOUT)

        log.info("✅ المتصفح جاهز")
        return self.context

    async def close(self):
        if self.context:
            try:
                await self.context.close()
            except Exception:
                pass
        if self.playwright:
            await self.playwright.stop()
        log.info("تم إغلاق المتصفح")
