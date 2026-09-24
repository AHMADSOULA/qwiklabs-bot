from utils.logger import get_logger
from utils.helpers import human_delay, human_move
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
        log.info("تسجيل الدخول إلى Cloud Console...")
        await page.goto("https://console.cloud.google.com", wait_until="domcontentloaded")
        await human_delay(3, 5)
        await take_screenshot(page, "cc_01_loaded")
        log.info(f"URL بعد الفتح: {page.url}")

        try:
            # 🔄 حلقة: نحاول 4 مرات باش نتعاملو مع signin المتكرر
            for attempt in range(4):
                log.info(f"--- محاولة {attempt + 1} ---")

                # 1. ننتظر الصفحة
                await self._wait_for_login_or_console(page)

                # 2. إذا كانت Sign in، سجل
                if await self._is_signin_page(page):
                    log.info(f"صفحة Sign in (محاولة {attempt + 1}) — بدء التسجيل")
                    await self._do_signin(page, self.username, self.password)
                    await human_delay(4, 6)
                    await take_screenshot(page, f"cc_after_signin_{attempt}")

                # 3. نتعاملو مع Welcome إذا كانت
                welcome_handled = await self._handle_welcome_page(page)
                if welcome_handled:
                    await human_delay(4, 6)
                    await take_screenshot(page, f"cc_after_welcome_{attempt}")

                # 4. إذا وصلنا للـ Console الحقيقي، نخرجو
                if await self._is_console_ready(page):
                    log.info(f"✅ وصلنا للـ Console فـ المحاولة {attempt + 1}")
                    break

                # 5. ننتظر شوية قبل المحاولة الجاية
                await human_delay(3, 5)

            # 6. نتأكدو من Console
            await self._wait_for_console(page)
            log.info(f"✅ URL النهائي: {page.url}")
            return page

        except Exception as e:
            log.error(f"فشل تسجيل الدخول: {e}")
            await take_screenshot(page, "cc_error")
            raise

    async def _is_console_ready(self, page) -> bool:
        """يتحقق واش وصلنا لـ Console الحقيقي"""
        url = page.url
        if "console.cloud.google.com" not in url:
            return False
        if "signin" in url.lower() or "accounts.google.com" in url:
            return False
        if "project=" in url:
            return True
        if "/home/" in url or "/welcome" in url:
            return True
        return False

    async def _wait_for_login_or_console(self, page, timeout: int = 25000):
        try:
            await page.wait_for_function(
                """() => {
                    return document.querySelector('input[type="email"]') ||
                           document.querySelector('input[type="text"]') ||
                           document.querySelector('input[type="password"]') ||
                           window.location.href.includes('console.cloud.google.com');
                }""",
                timeout=timeout,
            )
        except Exception:
            log.warning("Timeout فـ انتظار الصفحة")
        await human_delay(2, 3)

    async def _is_signin_page(self, page) -> bool:
        url = page.url
        if "accounts.google.com" in url:
            return True
        if "signin" in url.lower():
            return True
        for sel in [
            'input[type="email"]',
            'input[type="text"][name="identifier"]',
            'input[name="identifier"]',
            'input[type="password"]',
        ]:
            try:
                if await page.locator(sel).count() > 0:
                    return True
            except Exception:
                pass
        return False

    async def _do_signin(self, page, username: str, password: str):
        """تسجيل دخول ذكي"""

        # نحاول نعمر email
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

        if email_filled:
            await self._click_next(page, "email")
            await human_delay(3, 5)

        # نحاول نعمر password
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

        if password_filled:
            await self._click_next(page, "password")
            await human_delay(4, 7)

        if not email_filled and not password_filled:
            log.warning("ما لقيتش حتى حقل")

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

    async def _handle_welcome_page(self, page, max_attempts: int = 2) -> bool:
        """يتعامل مع صفحة Welcome. يرجع True إذا ضغط Accept."""
        for attempt in range(max_attempts):
            await human_delay(3, 5)

            # طريقة 1: JS click (أقوى)
            try:
                clicked = await page.evaluate("""
                    () => {
                        const allClickable = document.querySelectorAll(
                            'button, a, [role="button"], input[type="submit"]'
                        );
                        for (const el of allClickable) {
                            const text = (el.innerText || el.value || el.textContent || '').trim().toLowerCase();
                            if (text.includes('accept') || 
                                text.includes('agree') || 
                                text.includes('confirm') ||
                                text.includes('got it') ||
                                text.includes('قبول') ||
                                text.includes('موافق')) {
                                el.click();
                                return el.innerText || 'clicked';
                            }
                        }
                        return null;
                    }
                """)
                if clicked:
                    log.info(f"✅ ضغط على: {clicked}")
                    await human_delay(4, 6)
                    return True
            except Exception as e:
                log.warning(f"فشل JS click: {e}")

            # طريقة 2: Playwright locators
            accept_selectors = [
                'button:has-text("Accept")',
                'button:has-text("I agree")',
                'button:has-text("Agree")',
                'a:has-text("Accept")',
                'a:has-text("Agree")',
                '[role="button"]:has-text("Accept")',
                '[role="button"]:has-text("Agree")',
                'button:has-text("Confirm")',
                'button:has-text("Got it")',
                'button:has-text("Continue")',
                'button:has-text("OK")',
            ]

            for sel in accept_selectors:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        log.info(f"✅ لقيت: {sel}")
                        await el.click(force=True)
                        await human_delay(4, 6)
                        return True
                except Exception:
                    continue

            break
        return False

    async def _wait_for_console(self, page, timeout: int = 90000):
        log.info("انتظار تحميل Cloud Console...")
        try:
            await page.wait_for_function(
                """() => {
                    const url = window.location.href;
                    return url.includes('console.cloud.google.com') &&
                           !url.includes('signin') &&
                           !url.includes('accounts.google.com');
                }""",
                timeout=timeout,
            )
        except Exception:
            log.warning("Timeout فـ انتظار Console")
        await human_delay(3, 5)
        await take_screenshot(page, "cc_console_ready")
