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
            # 1. انتظر ملي تبان الصفحة (إما Sign in أو Console)
            await self._wait_for_login_or_console(page)

            # 2. إذا كان فـ صفحة Sign in، سجل دخول
            if await self._is_signin_page(page):
                log.info("صفحة Sign in — بدء التسجيل")
                await self._do_signin(page, username, password)
            else:
                log.info("دخلنا مباشرة للـ Console")

            # 3. انتظر Console
            await self._wait_for_console(page)

            log.info(f"✅ URL الحالي: {page.url}")
            return page

        except Exception as e:
            log.error(f"فشل تسجيل الدخول: {e}")
            await take_screenshot(page, "cc_error")
            raise

    async def _wait_for_login_or_console(self, page, timeout: int = 20000):
        """ينتظر إما صفحة Sign in أو Console"""
        try:
            await page.wait_for_function(
                """() => {
                    return document.querySelector('input[type="email"]') ||
                           document.querySelector('input[type="text"]') ||
                           document.querySelector('[data-test-id="console"]') ||
                           window.location.href.includes('console.cloud.google.com/home') ||
                           document.title.includes('Cloud Console');
                }""",
                timeout=timeout,
            )
        except Exception:
            log.warning("ما لقيتش لا Sign in لا Console — غادي نحاول نكمل")
        await human_delay(2, 3)

    async def _is_signin_page(self, page) -> bool:
        """يتحقق واش الصفحة هي Sign in"""
        url = page.url
        if "accounts.google.com" in url:
            return True
        if "console.cloud.google.com" in url and "signin" in url.lower():
            return True

        # فحص وجود حقل إيميل
        for sel in ['input[type="email"]', 'input[type="text"][name="identifier"]', 'input[name="identifier"]']:
            try:
                if await page.locator(sel).count() > 0:
                    return True
            except Exception:
                pass
        return False

    async def _do_signin(self, page, username: str, password: str):
        """ينفذ تسجيل الدخول خطوة خطوة"""

        # ====== الخطوة 1: الإيميل ======
        email_filled = False

        # selectors مختلفة لحقل الإيميل
        email_selectors = [
            'input[type="email"]',
            'input[type="text"][name="identifier"]',
            'input[name="identifier"]',
            'input[autocomplete="username"]',
        ]

        for sel in email_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    log.info(f"✅ لقيت حقل الإيميل: {sel}")
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
            await take_screenshot(page, "cc_no_email_field")
            raise RuntimeError("ما لقيتش حقل الإيميل فـ صفحة Sign in")

        # كليك على Next
        await self._click_next(page, "email")
        await human_delay(3, 5)

        # ====== الخطوة 2: كلمة السر ======
        password_filled = False
        password_selectors = [
            'input[type="password"]',
            'input[name="password"]',
            'input[autocomplete="current-password"]',
        ]

        for sel in password_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    log.info(f"✅ لقيت حقل كلمة السر: {sel}")
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
            await take_screenshot(page, "cc_no_password_field")
            raise RuntimeError("ما لقيتش حقل كلمة السر")

        # كليك على Next
        await self._click_next(page, "password")
        await human_delay(4, 7)
        await take_screenshot(page, "cc_after_password")

    async def _click_next(self, page, step: str):
        """كيضغط على زر Next / التالي"""
        next_selectors = [
            '#identifierNext',
            '#passwordNext',
            'button:has-text("Next")',
            'button:has-text("التالي")',
            'div[role="button"]:has-text("Next")',
            'button[type="submit"]',
        ]
        for sel in next_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    log.info(f"كليك على {sel} ({step})")
                    await human_move(page)
                    await el.click()
                    return
            except Exception:
                continue
        log.warning(f"ما لقيتش زر Next ({step})")

    async def _wait_for_console(self, page, timeout: int = 60000):
        """ينتظر تحميل Cloud Console"""
        log.info("انتظار تحميل Cloud Console...")
        try:
            await page.wait_for_function(
                """() => {
                    return window.location.href.includes('console.cloud.google.com') &&
                           !window.location.href.includes('signin') &&
                           !window.location.href.includes('accounts.google.com');
                }""",
                timeout=timeout,
            )
        except Exception:
            log.warning("Timeout فـ انتظار Console — غادي نكمل")
        await human_delay(3, 5)
        await take_screenshot(page, "cc_console_ready")
