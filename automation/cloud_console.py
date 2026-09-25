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

        # ✅ حلقة كبيرة: نحاول 6 مرات
        for attempt in range(6):
            log.info(f"========== محاولة {attempt + 1} ==========")
            await human_delay(2, 4)
            await take_screenshot(page, f"cc_attempt_{attempt}")
            current_url = page.url
            log.info(f"URL: {current_url}")

            # 1. Console جاهز؟ → خلاص
            if await self._is_console_ready(page):
                log.info("✅ وصلنا للـ Console!")
                await self._wait_for_console(page, timeout=30000)
                return page

            # 2. Welcome page؟ → نقبل الشروط
            if await self._is_welcome_page(page):
                log.info("📋 Welcome — نضغط Accept")
                clicked = await self._handle_welcome_page(page)
                if clicked:
                    await human_delay(5, 8)
                    continue
                else:
                    log.warning("ما لقيتش زر Accept")
                    await human_delay(3, 5)
                    continue

            # 3. Sign in؟ → نسجلو
            if await self._is_signin_page(page):
                log.info("🔑 Sign in")

                # حل CAPTCHA أولاً
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
                    log.warning(f"CAPTCHA: {e}")

                # نسجلو email + password
                try:
                    await self._do_signin(page, self.username, self.password)
                    await human_delay(5, 8)
                    await take_screenshot(page, f"cc_after_signin_{attempt}")
                except Exception as e:
                    log.warning(f"فشل signin: {e}")
                    await human_delay(3, 5)
                continue

            # 4. Welcome to your new account (TOS)؟
            if "workspacetermsofservice" in current_url.lower() or "speedbump" in current_url.lower():
                log.info("📋 TOS — نضغط Accept")
                await self._handle_welcome_page(page)
                await human_delay(5, 8)
                continue

            # 5. Verify؟
            if await self._has_verify_required(page):
                await take_screenshot(page, f"cc_verify_{attempt}")
                raise RuntimeError("❌ Google كتطلب verify")

            # 6. كلمة سر غلط؟
            if await self._has_wrong_password_error(page):
                await take_screenshot(page, f"cc_wrong_pwd_{attempt}")
                raise RuntimeError("❌ كلمة السر غلط")

            # صفحة غير معروفة → نستنى
            log.warning(f"❓ صفحة غير معروفة: {current_url[:100]}")
            await human_delay(4, 6)

        # بعد 6 محاولات
        await take_screenshot(page, "cc_final_fail")
        raise RuntimeError(
            f"❌ فشل بعد 6 محاولات\n"
            f"URL: {page.url[:200]}"
        )

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
        if "terms of service" in text and "accept" in text:
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
        if "accounts.google.com" in url and "workspaceterms" not in url and "speedbump" not in url:
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

        # ===== EMAIL =====
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
                log.info(f"✅ email field: {sel}")
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

                # طريقة بديلة
                await el.click()
                await page.keyboard.type(username, delay=50)
                await human_delay(0.3, 0.8)
                val = await el.input_value()
                if val.strip():
                    email_filled = True
                    break
            except Exception as e:
                log.warning(f"{sel}: {e}")
                continue

        if not email_filled:
            raise RuntimeError("❌ فشل email")

        await self._click_next(page, "email")
        await human_delay(4, 7)
        await take_screenshot(page, "cc_after_email")

        # ===== CAPTCHA بعد email =====
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
                log.info("✅ CAPTCHA solved")
                await human_delay(5, 7)
        except Exception as e:
            log.warning(f"CAPTCHA: {e}")

        # ===== PASSWORD =====
        await human_delay(2, 4)
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
                log.info(f"✅ pwd field: {sel}")
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
            except Exception:
                continue

        if not password_filled:
            log.warning("⚠️ ما لقيتش pwd field")
            # يمكن خاصنا نحلو CAPTCHA أولاً
            try:
                from automation.captcha_solver import detect_and_solve_captcha
                from config import config
                await detect_and_solve_captcha(
                    page, config.CAPTCHA_USERID, config.CAPTCHA_APIKEY
                )
                await human_delay(4, 6)

                # نعاودو نجربو
                for sel in ['input[type="password"]', 'input[name="password"]']:
                    try:
                        el = page.locator(sel).first
                        if await el.count() > 0 and await el.is_visible():
                            await el.click()
                            await human_delay(0.5, 1.0)
                            await el.fill("")
                            await el.fill(password)
                            await human_delay(0.3, 0.8)
                            val = await el.input_value()
                            if val.strip():
                                password_filled = True
                                break
                    except Exception:
                        continue
            except Exception:
                pass

        if not password_filled:
            raise RuntimeError("❌ فشل pwd")

        await self._click_next(page, "password")
        await human_delay(5, 8)
        await take_screenshot(page, "cc_after_pwd")
        log.info("✅ email + password done")

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
                    log.info(f"كليك {sel} ({step})")
                    await el.click()
                    return
            except Exception:
                continue

    async def _handle_welcome_page(self, page) -> bool:
        await human_delay(3, 5)
        # JS click
        try:
            clicked = await page.evaluate("""
                () => {
                    const all = document.querySelectorAll('button, a, [role="button"], input[type="submit"]');
                    for (const el of all) {
                        const t = (el.innerText || el.value || '').trim().toLowerCase();
                        if (t.includes('accept') || t.includes('agree') ||
                            t.includes('confirm') || t.includes('got it') ||
                            t.includes('i agree') || t.includes('continue')) {
                            el.click();
                            return t;
                        }
                    }
                    return null;
                }
            """)
            if clicked:
                log.info(f"✅ ضغط: {clicked}")
                await human_delay(5, 8)
                return True
        except Exception as e:
            log.warning(f"JS: {e}")

        # Playwright
        for sel in [
            'button:has-text("Accept")',
            'button:has-text("I agree")',
            'button:has-text("Agree")',
            'button:has-text("Confirm")',
            'button:has-text("Got it")',
            'button:has-text("Continue")',
            'a:has-text("Accept")',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    log.info(f"✅ كليك {sel}")
                    await el.click(force=True)
                    await human_delay(5, 8)
                    return True
            except Exception:
                continue
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
            log.warning("Timeout")
        await human_delay(3, 5)
        await take_screenshot(page, "cc_ready")
