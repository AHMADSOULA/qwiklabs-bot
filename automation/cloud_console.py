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

        for attempt in range(10):
            log.info(f"========== محاولة {attempt + 1} ==========")
            await human_delay(2, 4)
            await take_screenshot(page, f"cc_attempt_{attempt}")

            url = page.url
            log.info(f"URL: {url}")

            # ========== 1. Console ready ==========
            if await self._is_console_ready(page):
                log.info("✅ Console ready!")
                await self._wait_for_console(page, timeout=30000)
                return page

            # ========== 2. Welcome/TOS/Speedbump ==========
            if await self._is_welcome_page(page):
                log.info("📋 Welcome/TOS — نحاول Accept")
                clicked = await self._handle_welcome_page_hard(page)
                if clicked:
                    await human_delay(5, 8)
                    continue
                else:
                    log.warning("⚠️ ما لقيتش Accept — Enter")
                    try:
                        await page.keyboard.press("End")
                        await human_delay(1, 2)
                        await page.keyboard.press("Enter")
                        await human_delay(4, 6)
                    except Exception:
                        pass
                    continue

            # ========== 3. Verify؟ ==========
            if await self._has_verify_required(page):
                await take_screenshot(page, f"cc_verify_{attempt}")
                raise RuntimeError("❌ Google كتطلب verify phone/email")

            # ========== 4. كلمة سر غلط؟ ==========
            if await self._has_wrong_password_error(page):
                raise RuntimeError("❌ كلمة السر غلط")

            # ========== 5. Sign in ==========
            if await self._is_signin_page(page):
                log.info("🔑 Sign in")

                # ✅ 5.1 نحل CAPTCHA أولاً
                captcha_solved = await self._try_solve_captcha(page, attempt)
                if captcha_solved:
                    log.info("✅ CAPTCHA solved — continue")
                    await human_delay(4, 6)
                    continue

                # ✅ 5.2 نتحقق واش كاين حقل email
                has_email = await self._has_email_field(page)
                has_password = await self._has_password_field(page)

                log.info(f"   email field: {has_email}, pwd field: {has_password}")

                if has_email:
                    # كتب email
                    try:
                        await self._fill_email(page, self.username)
                        await human_delay(1, 2)
                        await self._click_next(page, "email")
                        await human_delay(4, 6)
                        await take_screenshot(page, f"cc_after_email_{attempt}")

                        # بعد email → نحل CAPTCHA
                        solved = await self._try_solve_captcha(page, attempt)
                        if solved:
                            await human_delay(4, 6)
                        continue
                    except Exception as e:
                        log.warning(f"email: {e}")
                        await human_delay(2, 3)
                        continue

                if has_password:
                    # كتب password
                    try:
                        await self._fill_password(page, self.password)
                        await human_delay(1, 2)
                        await self._click_next(page, "password")
                        await human_delay(4, 6)
                        await take_screenshot(page, f"cc_after_pwd_{attempt}")
                        continue
                    except Exception as e:
                        log.warning(f"pwd: {e}")
                        await human_delay(2, 3)
                        continue

                # ما كانش حقول → ممكن الصفحة مازال كتحمل
                log.warning("⚠️ ما كاينش حقول — نستنى")
                await human_delay(5, 8)
                continue

            log.warning(f"❓ صفحة غير معروفة: {url[:100]}")
            await human_delay(4, 6)

        await take_screenshot(page, "cc_final_fail")
        raise RuntimeError(f"❌ فشل\nURL: {page.url[:200]}")

    # ==================== CAPTCHA Helper ====================

    async def _try_solve_captcha(self, page, attempt: int) -> bool:
        """يحاول يحل CAPTCHA إذا كان موجود"""
        try:
            # ✅ نفحص واش كاين CAPTCHA أولاً
            has_captcha = await page.evaluate("""
                () => {
                    const imgs = document.querySelectorAll('img');
                    for (const img of imgs) {
                        const src = (img.src || '').toLowerCase();
                        const alt = (img.alt || '').toLowerCase();
                        const id = (img.id || '').toLowerCase();
                        const cls = (img.className || '').toString().toLowerCase();
                        if (src.includes('captcha') || alt.includes('captcha') ||
                            id.includes('captcha') || cls.includes('captcha')) {
                            return true;
                        }
                    }
                    return false;
                }
            """)

            if not has_captcha:
                return False

            log.info("🚨 CAPTCHA detected — solving...")

            from automation.captcha_solver import detect_and_solve_captcha
            from config import config

            if not config.CAPTCHA_USERID or not config.CAPTCHA_APIKEY:
                log.warning("⚠️ CAPTCHA credentials missing!")
                return False

            solved = await detect_and_solve_captcha(
                page,
                config.CAPTCHA_USERID,
                config.CAPTCHA_APIKEY,
            )

            if solved:
                log.info(f"✅ CAPTCHA solved (attempt {attempt})")
                await take_screenshot(page, f"cc_captcha_solved_{attempt}")
                return True
            else:
                log.warning(f"⚠️ CAPTCHA not solved")
                return False
        except Exception as e:
            log.error(f"CAPTCHA error: {e}")
            return False

    # ==================== Field Detection ====================

    async def _has_email_field(self, page) -> bool:
        for sel in [
            'input[type="email"]',
            'input[type="text"][name="identifier"]',
            'input[name="identifier"]',
            'input[autocomplete="username"]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    return True
            except Exception:
                pass
        return False

    async def _has_password_field(self, page) -> bool:
        for sel in [
            'input[type="password"]',
            'input[name="password"]',
            'input[autocomplete="current-password"]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    return True
            except Exception:
                pass
        return False

    async def _fill_email(self, page, email: str):
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
                await el.fill(email)
                await human_delay(0.3, 0.8)
                val = await el.input_value()
                if val.strip():
                    return
                # محاولة ثانية
                await el.click()
                await page.keyboard.type(email, delay=50)
                await human_delay(0.3, 0.8)
                return
            except Exception:
                continue
        raise RuntimeError("ما لقيتش email field")

    async def _fill_password(self, page, password: str):
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
                    return
                await el.click()
                await page.keyboard.type(password, delay=50)
                await human_delay(0.3, 0.8)
                return
            except Exception:
                continue
        raise RuntimeError("ما لقيتش pwd field")

    # ==================== Page Detection ====================

    async def _get_body_text(self, page, max_len: int = 400):
        try:
            text = await page.inner_text("body")
            return text[:max_len].replace('\n', ' | ')
        except Exception:
            return ""

    async def _is_welcome_page(self, page) -> bool:
        url = page.url.lower()
        if "workspacetermsofservice" in url or "speedbump" in url:
            return True
        text = (await self._get_body_text(page)).lower()
        if "welcome to your new account" in text:
            return True
        if "terms of service" in text and "accept" in text:
            return True
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
        # إذا كاين أي حقل
        for sel in [
            'input[type="email"]',
            'input[type="password"]',
            'input[type="text"][name="identifier"]',
            'input[name="identifier"]',
        ]:
            try:
                if await page.locator(sel).count() > 0:
                    return True
            except Exception:
                pass
        return False

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

    async def _handle_welcome_page_hard(self, page) -> bool:
        log.info("🔍 نحاول نلقاو زر Accept...")
        await human_delay(3, 5)

        # JS click
        try:
            clicked = await page.evaluate("""
                () => {
                    const all = document.querySelectorAll('button, a, [role="button"], input[type="submit"]');
                    const keywords = ['accept', 'agree', 'confirm', 'got it',
                                     'i agree', 'continue', 'قبول', 'موافق'];
                    for (const el of all) {
                        const t = (el.innerText || el.value || el.textContent || '').trim().toLowerCase();
                        for (const kw of keywords) {
                            if (t.includes(kw)) {
                                el.click();
                                return el.innerText || el.value || 'clicked';
                            }
                        }
                    }
                    return null;
                }
            """)
            if clicked:
                log.info(f"✅ JS click: {clicked}")
                await human_delay(5, 8)
                return True
        except Exception as e:
            log.warning(f"JS: {e}")

        # Blue button
        try:
            clicked = await page.evaluate("""
                () => {
                    const all = document.querySelectorAll('button, input[type="submit"]');
                    for (const el of all) {
                        const bg = window.getComputedStyle(el).backgroundColor;
                        if (bg === 'rgb(26, 115, 232)' || bg === 'rgb(66, 133, 244)') {
                            el.click();
                            return 'blue';
                        }
                    }
                    return null;
                }
            """)
            if clicked:
                log.info(f"✅ blue button")
                await human_delay(5, 8)
                return True
        except Exception:
            pass

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
