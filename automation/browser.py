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


# ✅ حجب الموارد الثقيلة (صور، فيديو، خطوط) — توفير ذاكرة
async def _block_heavy_resources(route):
    try:
        rt = route.request.resource_type
        url = route.request.url.lower()
        # نسمحو captcha
        if 'captcha' in url or 'recaptcha' in url:
            await route.continue_()
            return
        if rt in ('image', 'media', 'font'):
            await route.abort()
        else:
            await route.continue_()
    except Exception:
        try:
            await route.continue_()
        except Exception:
            pass


class StealthBrowser:
    def __init__(self):
        self.playwright = None
        self.context = None

    async def start(self):
        self.playwright = await async_playwright().start()
        os.makedirs(config.CHROME_PROFILE_DIR, exist_ok=True)

        # ✅ args محسّنة للذاكرة — بحال GC.py
        args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",           # ⭐ مهم للذاكرة
            "--disable-gpu",                     # ⭐ مهم للذاكرة
            "--disable-software-rasterizer",
            "--disable-accelerated-2d-canvas",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-infobars",
            "--disable-extensions",
            "--disable-plugins",
            "--disable-sync",
            "--disable-translate",
            "--disable-default-apps",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-backgrounding-occluded-windows",
            "--mute-audio",
            "--hide-scrollbars",
            "--metrics-recording-only",
            "--safebrowsing-disable-auto-update",
            "--renderer-process-limit=1",        # ⭐ مهم
            "--js-flags=--max-old-space-size=256",  # ⭐ حد الذاكرة
            "--window-size=1280,720",
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
            "viewport": {"width": 1280, "height": 720},
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

        try:
            self.context = await self.playwright.chromium.launch_persistent_context(**launch_kwargs)
        except Exception as e:
            log.warning(f"launch فشل: {e}")
            launch_kwargs.pop("channel", None)
            self.context = await self.playwright.chromium.launch_persistent_context(**launch_kwargs)

        await self.context.add_init_script(STEALTH_JS)

        # ✅ حجب الموارد
        await self.context.route("**/*", _block_heavy_resources)

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
            try:
                await self.playwright.stop()
            except Exception:
                pass
        log.info("تم إغلاق المتصفح")
