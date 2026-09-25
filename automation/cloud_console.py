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

        async def login(self, username: str, password: str,
                    user_id: int = None, sender=None, context=None):
        self.username = username
        self.password = password

        page = await self.context.new_page()
        log.info("تسجيل الدخول...")
        await page.goto("https://console.cloud.google.com", wait_until="domcontentloaded")
        await human_delay(3, 5)
        await take_screenshot(page, "cc_01_loaded")
        log.info(f"URL: {page.url}")

        try:
            for attempt in range(3):
                log.info(f"===== محاولة {attempt + 1} =====")
                await human_delay(2, 3)
                await take_screenshot(page, f"cc_iter_{attempt}")
                log.info(f"URL: {page.url}")

                # Console ready?
                if await self._is_console_ready(page):
                    log.info(f"✅ وصلنا للـ Console")
                    break

                # Sign in?
                if await self._is_signin_page(page):
                    log.info(f"🔑 Sign in")

                    # نحل CAPTCHA أولاً
                    try:
                        from automation.captcha_solver import detect_and_solve_captcha
                        from config import config
                        await human_delay(1, 2)
                        solved = await detect_and_solve_captcha(
                            page,
                            config.CAPTCHA_USERID,
                            config.CAPTCHA_APIKEY,
                        )
                        if solved:
                            log.info("✅ تم حل CAPTCHA")
                            await human_delay(4, 6)
                            continue
                    except Exception as e:
                        log.warning(f"فشل CAPTCHA: {e}")

                    # نسجلو
                    try:
                        await self._do_signin(page, self.username, self.password)
                        await human_delay(5, 7)
                        await take_screenshot(page, f"cc_after_signin_{attempt}")
                    except Exception as e:
                        log.warning(f"فشل sign in: {e}")

                    continue

                # Welcome?
                if await self._is_welcome_page(page):
                    log.info("📋 Welcome — نضغط Accept")
                    clicked = await self._handle_welcome_page(page)
                    if clicked:
                        await human_delay(4, 6)
                    continue

                # كلمة سر غلط؟
                if await self._has_wrong_password_error(page):
                    await take_screenshot(page, f"cc_wrong_pwd_{attempt}")
                    raise RuntimeError("❌ كلمة السر غلط. جدد الرابط.")

                # Verify?
                if await self._has_verify_required(page):
                    await take_screenshot(page, f"cc_verify_{attempt}")
                    raise RuntimeError("❌ Google كتطلب verify.")

                log.warning(f"❓ صفحة غير معروفة: {page.url[:100]}")
                await human_delay(3, 5)

            await self._wait_for_console(page, timeout=30000)
            log.info(f"✅ URL النهائي: {page.url}")
            return page

        except Exception as e:
            log.error(f"فشل تسجيل الدخول: {e}")
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
            for txt in ['incorrect password', 'wrong password']:
                if txt in content:
                    return True
        except Exception:
            pass
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
                if await page.locator(sel).count() > 0:
                    return True
            except Exception:
                pass
        return False

    async def _do_signin(self, page, username: str, password: str):
        await take_screenshot(page, "cc_before_signin")

        # Email
        email_filled = False
        for sel in [
            'input[type="email"]',
            'input[type="text"][name="identifier"]',
            'input[name="identifier"]',
            'input[autocomplete="username"]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() == 0 or not await el.is_visible():
                    continue
                log.info(f"✅ حقل الإيميل: {sel}")
                await el.click()
                await human_delay(0.5, 1.0)
                await el.fill("")
                await human_delay(0.2, 0.5)
                await el.fill(username)
                await human_delay(0.3, 0.8)
                val = await el.input_value()
                if val.strip():
                    email_filled = True
                    break

                await el.click()
                await page.keyboard.type(username, delay=50)
                await human_delay(0.3, 0.8)
                val = await el.input_value()
                if val.strip():
                    email_filled = True
                    break
            except Exception as e:
                log.warning(f"فشل {sel}: {e}")
                continue

        if not email_filled:
            body_text = await self._get_body_text(page)
            raise RuntimeError(
                f"❌ ما قدرتش نكتب الإيميل\nURL: {page.url[:150]}"
            )

        await self._click_next(page, "email")
        await human_delay(4, 6)
        await take_screenshot(page, "cc_after_email_next")

        # CAPTCHA بعد email
        try:
            from automation.captcha_solver import detect_and_solve_captcha
            from config import config
            await human_delay(1, 2)
            solved = await detect_and_solve_captcha(
                page,
                config.CAPTCHA_USERID,
                config.CAPTCHA_APIKEY,
            )
            if solved:
                log.info("✅ تم حل CAPTCHA")
                await human_delay(4, 6)
                await take_screenshot(page, "cc_after_captcha")
        except Exception as e:
            log.warning(f"فشل CAPTCHA: {e}")

        # Password
        await human_delay(2, 3)
        await take_screenshot(page, "cc_before_pwd")

        password_filled = False
        for sel in [
            'input[type="password"]',
            'input[name="password"]',
            'input[autocomplete="current-password"]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() == 0 or not await el.is_visible():
                    continue
                log.info(f"✅ حقل كلمة السر: {sel}")
                await el.click()
                await human_delay(0.5, 1.0)
                await el.fill("")
                await human_delay(0.2, 0.5)
                await el.fill(password)
                await human_delay(0.3, 0.8)
                val = await el.input_value()
                if val.strip():
                    password_filled = True
                    break

                await el.click()
                await page.keyboard.type(password, delay=50)
                await human_delay(0.3, 0.8)
                val = await el.input_value()
                if val.strip():
                    password_filled = True
                    break
            except Exception as e:
                log.warning(f"فشل pwd {sel}: {e}")
                continue

        if not password_filled:
            body_text = await self._get_body_text(page)
            await take_screenshot(page, "cc_no_pwd")
            raise RuntimeError(
                f"❌ ما قدرتش نكتب كلمة السر\nURL: {page.url[:150]}"
            )

        await self._click_next(page, "password")
        await human_delay(4, 7)
        await take_screenshot(page, "cc_after_pwd_next")
        log.info("✅ تم إدخال email + password")

    async def _click_next(self, page, step: str):
        for sel in [
            '#identifierNext',
            '#passwordNext',
            '#captchaNext',
            'button:has-text("Next")',
            'button:has-text("التالي")',
            'div[role="button"]:has-text("Next")',
            'button[type="submit"]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    log.info(f"كليك على {sel} ({step})")
                    await el.click()
                    return
            except Exception:
                continue

    async def _handle_welcome_page(self, page, max_attempts: int = 2) -> bool:
        for attempt in range(max_attempts):
            await human_delay(3, 5)
            try:
                clicked = await page.evaluate("""
                    () => {
                        const all = document.querySelectorAll(
                            'button, a, [role="button"], input[type="submit"]'
                        );
                        for (const el of all) {
                            const text = (el.innerText || el.value || el.textContent || '').trim().toLowerCase();
                            if (text.includes('accept') || text.includes('agree') ||
                                text.includes('confirm') || text.includes('got it')) {
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
            except Exception:
                pass
            break
        return False

    async def _wait_for_console(self, page, timeout: int = 60000):
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
            log.warning("Timeout Console")
        await human_delay(3, 5)
        await take_screenshot(page, "cc_console_ready")
