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
            # 🔄 حلقة ذكية: نحاول 3 مرات
            for attempt in range(3):
                log.info(f"--- محاولة {attempt + 1} ---")
                await self._wait_for_login_or_console(page)

                # 🔍 فحص: هل توجد رسالة خطأ كلمة السر؟
                if await self._has_wrong_password_error(page):
                    log.warning("⚠️ كلمة السر غلط! Google رفضت الجلسة")
                    await take_screenshot(page, f"cc_wrong_pwd_{attempt}")
                    raise RuntimeError(
                        "❌ كلمة السر غير صحيحة أو انتهت صلاحيتها.\n"
                        "الرابط صالح 5 سوايع فقط. جدد الرابط."
                    )

                # 🔍 فحص: هل توجد رسالة verify phone/email؟
                if await self._has_verify_required(page):
                    log.warning("⚠️ Google كتطلب verify phone/email")
                    await take_screenshot(page, f"cc_verify_{attempt}")
                    raise RuntimeError(
                        "❌ Google كتطلب التحقق من الهاتف/الإيميل.\n"
                        "خاصك تسجل دخول يدوياً أول مرة.\n"
                        "شوف: https://console.cloud.google.com"
                    )

                # 1. إذا كانت Sign in → سجل
                if await self._is_signin_page(page):
                    log.info(f"صفحة Sign in (محاولة {attempt + 1})")
                    await self._do_signin(page, self.username, self.password)
                    await human_delay(5, 7)
                    await take_screenshot(page, f"cc_after_signin_{attempt}")

                # 2. نتعاملو مع Welcome
                await self._handle_welcome_page(page)
                await human_delay(4, 6)

                # 3. إذا وصلنا للـ Console → خلاص
                if await self._is_console_ready(page):
                    log.info(f"✅ وصلنا للـ Console فـ المحاولة {attempt + 1}")
                    break

                # 4. إذا رجع لـ Sign in بعد Accept → نوقف
                #    حيت كيعاود نفس المشكل
                if await self._is_signin_page(page):
                    log.warning("رجع لـ Sign in بعد Accept")
                    await take_screenshot(page, f"cc_loop_{attempt}")
                    # ننتظر شوية قبل المحاولة التالية
                    await human_delay(3, 5)

            await self._wait_for_console(page, timeout=30000)
            log.info(f"✅ URL النهائي: {page.url}")
            return page

        except Exception as e:
            log.error(f"فشل تسجيل الدخول: {e}")
            await take_screenshot(page, "cc_error")
            raise

    # ==========================================
    # 🔍 دوال الفحص
    # ==========================================

    async def _has_wrong_password_error(self, page) -> bool:
        """يتحقق واش Google عرضت رسالة كلمة سر غلط"""
        try:
            error_texts = [
                'Incorrect password',
                'Wrong password',
                'كلمة السر غير صحيحة',
                'Try again or click',
            ]
            content = await page.content()
            for txt in error_texts:
                if txt.lower() in content.lower():
                    return True
        except Exception:
            pass
        return False

    async def _has_verify_required(self, page) -> bool:
        """يتحقق واش Google كتطلب verify phone/email"""
        try:
            verify_texts = [
                'Verify it',
                'verify your',
                'Confirm your',
                'Enter the code',
                'Get a verification code',
                '2-Step Verification',
                'phone number',
                'recovery email',
            ]
            content = await page.content()
            for txt in verify_texts:
                if txt.lower() in content.lower():
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
        # ===== Email =====
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
                    await el.fill("")  # امسح الأول
                    await el.fill(username)
                    await human_delay(0.5, 1.2)
                    email_filled = True
                    break
            except Exception:
                continue

        if email_filled:
            await self._click_next(page, "email")
            await human_delay(3, 5)

        # ===== Password =====
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
                    await el.fill("")
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
        for attempt in range(max_attempts):
            await human_delay(3, 5)

            # طريقة 1: JS click
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

            # طريقة 2: locators
            accept_selectors = [
                'button:has-text("Accept")',
                'button:has-text("I agree")',
                'button:has-text("Agree")',
                'button:has-text("Confirm")',
                'button:has-text("Got it")',
                'button:has-text("Continue")',
                'a:has-text("Accept")',
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

    async def _wait_for_console(self, page, timeout: int = 60000):
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
