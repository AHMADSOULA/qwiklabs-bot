from utils.logger import get_logger
from utils.helpers import human_delay, human_move
from utils.screenshot import take_screenshot

log = get_logger("CloudConsole")


class CloudConsole:
    def __init__(self, context):
        self.context = context

    async def login(self, username: str, password: str):
        page = await self.context.new_page()
        log.info("تسجيل الدخول إلى Cloud Console...")
        await page.goto("https://console.cloud.google.com", wait_until="domcontentloaded")
        await human_delay(3, 5)
        await take_screenshot(page, "cc_01_loaded")
        log.info(f"URL بعد الفتح: {page.url}")

        try:
            await self._wait_for_login_or_console(page)
            if await self._is_signin_page(page):
                log.info("صفحة Sign in — بدء التسجيل")
                await self._do_signin(page, username, password)
            else:
                log.info("دخلنا مباشرة للـ Console")

            # ✅ جديد: تعامل مع صفحة Welcome
            await self._handle_welcome_page(page)

            await self._wait_for_console(page)
            log.info(f"✅ URL الحالي: {page.url}")
            return page

        except Exception as e:
            log.error(f"فشل تسجيل الدخول: {e}")
            await take_screenshot(page, "cc_error")
            raise

    async def _wait_for_login_or_console(self, page, timeout: int = 20000):
        try:
            await page.wait_for_function(
                """() => {
                    return document.querySelector('input[type="email"]') ||
                           document.querySelector('input[type="text"]') ||
                           document.querySelector('[data-test-id="console"]') ||
                           window.location.href.includes('console.cloud.google.com') ||
                           document.title.includes('Cloud Console') ||
                           document.title.includes('Welcome');
                }""",
                timeout=timeout,
            )
        except Exception:
            log.warning("ما لقيتش لا Sign in لا Console")
        await human_delay(2, 3)

    async def _is_signin_page(self, page) -> bool:
        url = page.url
        if "accounts.google.com" in url:
            return True
        for sel in ['input[type="email"]', 'input[type="text"][name="identifier"]', 'input[name="identifier"]']:
            try:
                if await page.locator(sel).count() > 0:
                    return True
            except Exception:
                pass
        return False

    async def _do_signin(self, page, username: str, password: str):
        email_filled = False
        for sel in [
            'input[type="email"]',
            'input[type="text"][name="identifier"]',
            'input[name="identifier"]',
            'input[autocomplete="username"]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    log.info(f"✅ حقل الإيميل: {sel}")
                    await human_move(page)
                    await el.click()
                    await human_delay(0.3, 0.8)
                    await el.fill(username)
                    await human_delay(0.5, 1.2)
                    email_filled = True
                    break
            except Exception:
                continue
        if not email_filled:
            raise RuntimeError("ما لقيتش حقل الإيميل")
        await self._click_next(page, "email")
        await human_delay(3, 5)

        password_filled = False
        for sel in [
            'input[type="password"]',
            'input[name="password"]',
            'input[autocomplete="current-password"]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    log.info(f"✅ حقل كلمة السر: {sel}")
                    await human_move(page)
                    await el.click()
                    await human_delay(0.3, 0.8)
                    await el.fill(password)
                    await human_delay(0.5, 1.2)
                    password_filled = True
                    break
            except Exception:
                continue
        if not password_filled:
            raise RuntimeError("ما لقيتش حقل كلمة السر")
        await self._click_next(page, "password")
        await human_delay(4, 7)
        await take_screenshot(page, "cc_after_password")

    async def _click_next(self, page, step: str):
        for sel in [
            '#identifierNext',
            '#passwordNext',
            'button:has-text("Next")',
            'button:has-text("التالي")',
            'div[role="button"]:has-text("Next")',
            'button[type="submit"]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    log.info(f"كليك على {sel} ({step})")
                    await human_move(page)
                    await el.click()
                    return
            except Exception:
                continue

    async def _handle_welcome_page(self, page, max_attempts: int = 3):
        """يتعامل مع صفحة Welcome (الموافقة على الشروط)"""
        for attempt in range(max_attempts):
            await human_delay(2, 3)

            # فحص إذا كاين زر Accept
            accept_buttons = [
                'button:has-text("Accept")',
                'button:has-text("I agree")',
                'button:has-text("Agree")',
                'button:has-text("موافق")',
                'button:has-text("قبول")',
                'a:has-text("Accept")',
                'div[role="button"]:has-text("Accept")',
            ]

            clicked = False
            for sel in accept_buttons:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0 and await el.is_visible():
                        log.info(f"✅ لقيت زر Accept: {sel}")
                        await human_move(page)
                        await el.click()
                        clicked = True
                        await human_delay(4, 6)
                        break
                except Exception:
                    continue

            if clicked:
                await take_screenshot(page, f"cc_welcome_accepted_{attempt}")
                # انتظر التحويل
                await human_delay(3, 5)
            else:
                # ما كاينش زر Accept
                break

    async def _wait_for_console(self, page, timeout: int = 90000):
        log.info("انتظار تحميل Cloud Console...")
        try:
            await page.wait_for_function(
                """() => {
                    const url = window.location.href;
                    if (url.includes('console.cloud.google.com') &&
                        !url.includes('signin') &&
                        !url.includes('accounts.google.com') &&
                        !url.includes('welcome')) {
                        return true;
                    }
                    return false;
                }""",
                timeout=timeout,
            )
        except Exception:
            log.warning("Timeout فـ انتظار Console")
        await human_delay(3, 5)
        await take_screenshot(page, "cc_console_ready")
