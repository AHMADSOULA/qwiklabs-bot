import asyncio
from utils.logger import get_logger
from utils.helpers import human_delay
from utils.screenshot import take_screenshot

log = get_logger("CloudConsole")


class CloudConsole:
    def __init__(self, context):
        self.context = context
        self.username = None
        self.password = None

    async def login(self, username: str, password: str):
        self.username = username
        self.password = password

        page = await self.context.new_page()
        log.info("تسجيل الدخول...")
        await page.goto("https://console.cloud.google.com", wait_until="domcontentloaded")
        await human_delay(3, 5)
        await take_screenshot(page, "cc_01_loaded")

        try:
            for attempt in range(3):
                log.info(f"=== محاولة {attempt + 1} ===")
                await human_delay(2, 3)
                await take_screenshot(page, f"cc_iter_{attempt}")

                if await self._is_console_ready(page):
                    log.info(f"✅ Console")
                    break

                if await self._is_signin_page(page):
                    log.info(f"🔑 Sign in")
                    try:
                        from automation.captcha_solver import detect_and_solve_captcha
                        from config import config
                        await human_delay(1, 2)
                        solved = await detect_and_solve_captcha(
                            page, config.CAPTCHA_USERID, config.CAPTCHA_APIKEY
                        )
                        if solved:
                            log.info("✅ CAPTCHA solved")
                            await human_delay(4, 6)
                            continue
                    except Exception as e:
                        log.warning(f"CAPTCHA: {e}")

                    try:
                        await self._do_signin(page, self.username, self.password)
                        await human_delay(5, 7)
                    except Exception as e:
                        log.warning(f"signin: {e}")
                    continue

                if await self._is_welcome_page(page):
                    log.info("📋 Welcome")
                    await self._handle_welcome_page(page)
                    await human_delay(4, 6)
                    continue

                if await self._has_wrong_password_error(page):
                    raise RuntimeError("❌ كلمة السر غلط")

                if await self._has_verify_required(page):
                    raise RuntimeError("❌ verify مطلوب")

                await human_delay(3, 5)

            await self._wait_for_console(page, timeout=30000)
            return page
        except Exception as e:
            log.error(f"فشل: {e}")
            await take_screenshot(page, "cc_error")
            raise

    async def _get_body_text(self, page, max_len: int = 400):
        try:
            text = await page.inner_text("body")
            return text[:max_len].replace('\n', ' | ')
        except Exception:
            return ""

    async def _is_welcome_page(self, page) -> bool:
        text = (await self._get_body_text(page)).lower()
        if "welcome to your new account" in text:
            return True
        try:
            for sel in [
                'button:has-text("Accept")',
                'button:has-text("I agree")',
                'button:has-text("Agree")',
            ]:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    return True
        except Exception:
            pass
        return False

    async def _has_wrong_password_error(self, page) -> bool:
        try:
            content = (await page.content()).lower()
            return 'incorrect password' in content or 'wrong password' in content
        except Exception:
            return False

    async def _has_verify_required(self, page) -> bool:
        try:
            content = (await page.content()).lower()
            for txt in ['verify it', 'verify your', 'enter the code', '2-step']:
                if txt in content:
                    return True
        except Exception:
            pass
        return False

    async def _is_console_ready(self, page) -> bool:
        url = page.url
        if "console.cloud.google.com" not in url:
            return False
        if "signin" in url.lower() or "accounts.google.com" in url:
            return False
        return True

    async def _is_signin_page(self, page) -> bool:
        url = page.url.lower()
        if "accounts.google.com" in url and "workspaceterms" not in url:
            return True
        for sel in [
            'input[type="email"]',
            'input[type="text"][name="identifier"]',
            'input[name="identifier"]',
        ]:
            try:
               
