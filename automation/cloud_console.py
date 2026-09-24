import asyncio
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
            # 🔄 حلقة رئيسية: نتعاملو مع كل الصفحات المحتملة
            for attempt in range(6):
                log.info(f"===== محاولة {attempt + 1} =====")
                await human_delay(2, 3)
                await self._wait_for_page_load(page)

                current_url = page.url
                log.info(f"URL الحالي: {current_url}")
                await take_screenshot(page, f"cc_iter_{attempt}")

                # 🚨 1. صفحة Welcome / Terms of Service
                if await self._is_welcome_or_tos_page(page):
                    log.info("📋 صفحة Welcome/Terms — نضغط Accept")
                    clicked = await self._handle_welcome_page(page)
                    if clicked:
                        await human_delay(4, 6)
                        continue

                # 🚨 2. صفحة Verify / 2FA
                if await self._has_verify_required(page):
                    log.warning("⚠️ verify phone")
                    await take_screenshot(page, f"cc_verify_{attempt}")
                    raise RuntimeError(
                        "❌ Google كتطلب التحقق من الهاتف.\n"
                        "سجل يدوياً أول مرة."
                    )

                # 🚨 3. كلمة سر غلط
                if await self._has_wrong_password_error(page):
                    await take_screenshot(page, f"cc_wrong_pwd_{attempt}")
                    raise RuntimeError("❌ كلمة السر غلط. جدد الرابط.")

                # ✅ 4. Console جاهز → خلاص
                if await self._is_console_ready(page):
                    log.info(f"✅ وصلنا للـ Console")
                    break

                # 🔑 5. صفحة Sign in
                if await self._is_signin_page(page):
                    log.info(f"🔑 صفحة Sign in (محاولة {attempt + 1})")
                    try:
                        await self._do_signin(page, self.username, self.password)
                        await human_delay(5, 7)
                        await take_screenshot(page, f"cc_after_signin_{attempt}")
                    except Exception as e:
                        log.warning(f"فشل sign in: {e}")
                        # نكمل الحلقة، يمكن الصفحة تبدلت
                        await human_delay(2, 3)
                        continue
                    continue

                # 🔄 6. صفحة Speedbump / Loading
                if "speedbump" in current_url or "loading" in (await self._get_body_text(page)).lower():
                    log.info("⏳ صفحة speedbump/loading — نستنى")
                    await human_delay(5, 7)
                    continue

                # ما عرفناش — نستنى و نعاود
                log.warning(f"❓ صفحة غير معروفة — نستنى")
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

    async def _is_welcome_or_tos_page(self, page) -> bool:
        """يتحقق واش الصفحة Welcome/Terms"""
        url = page.url.lower()
        if "workspacetermsofservice" in url or "speedbump" in url:
            return True

        text = (await self._get_body_text(page)).lower()
        if "welcome to your new account" in text:
            return True
        if "terms of service" in text and "welcome" in text:
            return True

        # 🔍 نتحقق واش كاين زر Accept
        try:
            for sel in [
                'button:has-text("Accept")',
                'button:has-text("I agree")',
                'button:has-text("Agree")',
                'button:has-text("Confirm")',
                'button:has-text("Got it")',
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
            for txt in ['incorrect password', 'wrong password', 'كلمة السر غير صحيحة']:
                if txt in content:
                    return True
        except Exception:
            pass
        return False

    async def _has_verify_required(self, page) -> bool:
        try:
            content = (await page.content()).lower()
            for txt in ['verify it', 'verify your', 'confirm your',
                        'enter the code', '2-step', '2 step',
                        'recovery email', 'verification code']:
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
        if "project=" in url:
            return True
        if "/home/" in url or "/welcome" in url:
            return True
        return False

    async def _wait_for_page_load(self, page, timeout: int = 15000):
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=timeout)
        except Exception:
            pass

    async def _is_signin_page(self, page) -> bool:
        url = page.url
        if "accounts.google.com" in url and "speedbump" not in url.lower():
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
        await take_screenshot(page, "cc_before_email")
        log.info(f"URL قبل email: {page.url}")

        # 🔍 نسجل الحقول
        try:
            inputs_info = await page.evaluate("""
                () => {
                    const inputs = document.querySelectorAll('input');
                    return Array.from(inputs).map(i => ({
                        type: i.type, name: i.name, id: i.id,
                        visible: i.offsetParent !== null,
                    }));
                }
            """)
            log.info(f"🔍 الحقول: {inputs_info}")
        except Exception:
            pass

        # ========== Email ==========
        email_filled = False
        email_selectors = [
            'input[type="email"]',
            'input[type="text"][name="identifier"]',
            'input[name="identifier"]',
            'input[autocomplete="username"]',
            'input[aria-label*="mail" i]',
            'input[jsname="YPqjbf"]',
            'input[type="text"]',
        ]

        for sel in email_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() == 0 or not await el.is_visible():
                    continue
                log.info(f"✅ حقل الإيميل: {sel}")
                await el.scroll_into_view_if_needed()
                await human_move(page)
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

                log.warning("fill ما خدمش — type")
                await el.click()
                await page.keyboard.type(username, delay=50)
                await human_delay(0.3, 0.8)
                val = await el.input_value()
                if val.strip():
                    email_filled = True
                    break

                log.warning("type ما خدمش — JS")
                await page.evaluate(
                    """(args) => {
                        const inputs = document.querySelectorAll('input');
                        for (const inp of inputs) {
                            if (inp.type === 'email' || inp.type === 'text' ||
                                inp.name === 'identifier' || inp.id === 'identifierId') {
                                inp.focus();
                                inp.value = args.val;
                                inp.dispatchEvent(new Event('input', { bubbles: true }));
                                return true;
                            }
                        }
                        return false;
                    }""",
                    {"val": username}
                )
                await human_delay(0.5, 1.0)
                val = await el.input_value()
                if val.strip():
                    email_filled = True
                    break
            except Exception as e:
                log.warning(f"فشل {sel}: {e}")
                continue

        await take_screenshot(page, "cc_after_email_attempt")

        if not email_filled:
            body_text = await self._get_body_text(page, 500)
            raise RuntimeError(
                f"❌ ما قدرتش نكتب الإيميل\n\n"
                f"🔗 URL:\n{page.url[:200]}\n\n"
                f"📄 النص:\n{body_text[:250]}"
            )

        await human_delay(0.5, 1.2)
        await self._click_next(page, "email")
        await human_delay(3, 5)
        await take_screenshot(page, "cc_after_email_next")

        # ========== CAPTCHA ==========
        try:
            from automation.captcha_solver import detect_and_solve_captcha
            from config import config
            await asyncio.sleep(2)
            solved = await detect_and_solve_captcha(
                page,
                config.CAPTCHA_USERID,
                config.CAPTCHA_APIKEY,
            )
            if solved:
                log.info("✅ حل CAPTCHA")
                await human_delay(4, 6)
                await take_screenshot(page, "cc_after_captcha")
        except Exception as e:
            log.warning(f"فشل حل CAPTCHA: {e}")

        # ========== Password ==========
        await human_delay(2, 4)
        await take_screenshot(page, "cc_before_pwd")
        log.info(f"URL قبل password: {page.url}")

        password_filled = False
        password_selectors = [
            'input[type="password"]',
            'input[name="password"]',
            'input[autocomplete="current-password"]',
            'input[aria-label*="password" i]',
        ]

        for sel in password_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() == 0 or not await el.is_visible():
                    continue
                log.info(f"✅ حقل كلمة السر: {sel}")
                await el.scroll_into_view_if_needed()
                await human_move(page)
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

                log.warning("fill ما خدمش — type")
                await el.click()
                await page.keyboard.type(password, delay=50)
                await human_delay(0.3, 0.8)
                val = await el.input_value()
                if val.strip():
                    password_filled = True
                    break

                log.warning("type ما خدمش — JS")
                await page.evaluate(
                    """(args) => {
                        const inp = document.querySelector('input[type="password"]');
                        if (inp) {
                            inp.focus();
                            inp.value = args.val;
                            inp.dispatchEvent(new Event('input', { bubbles: true }));
                            return true;
                        }
                        return false;
                    }""",
                    {"val": password}
                )
                await human_delay(0.5, 1.0)
                val = await el.input_value()
                if val.strip():
                    password_filled = True
                    break
            except Exception as e:
                log.warning(f"فشل pwd {sel}: {e}")
                continue

        await take_screenshot(page, "cc_after_pwd_attempt")

        if not password_filled:
            body_text = await self._get_body_text(page, 500)
            raise RuntimeError(
                f"❌ ما قدرتش نكتب كلمة السر\n\n"
                f"🔗 URL:\n{page.url[:200]}\n\n"
                f"📄 النص:\n{body_text[:250]}"
            )

        await human_delay(0.5, 1.2)
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
                    await human_move(page)
                    await el.click()
                    return
            except Exception:
                continue

    async def _handle_welcome_page(self, page, max_attempts: int = 3) -> bool:
        """يتعامل مع صفحة Welcome/Terms"""
        for attempt in range(max_attempts):
            await human_delay(3, 5)

            # طريقة 1: JS click
            try:
                clicked = await page.evaluate("""
                    () => {
                        const all = document.querySelectorAll(
                            'button, a, [role="button"], input[type="submit"]'
                        );
                        for (const el of all) {
                            const text = (el.innerText || el.value || el.textContent || '').trim().toLowerCase();
                            if (text.includes('accept') || text.includes('agree') ||
                                text.includes('confirm') || text.includes('got it') ||
                                text.includes('continue') || text.includes('i agree') ||
                                text.includes('قبول') || text.includes('موافق')) {
                                el.click();
                                return el.innerText || 'clicked';
                            }
                        }
                        return null;
                    }
                """)
                if clicked:
                    log.info(f"✅ ضغط على: {clicked}")
                    await human_delay(5, 7)
                    return True
            except Exception as e:
                log.warning(f"فشل JS click: {e}")

            # طريقة 2: Playwright locators
            for sel in [
                'button:has-text("Accept")',
                'button:has-text("I agree")',
                'button:has-text("Agree")',
                'button:has-text("Confirm")',
                'button:has-text("Got it")',
                'button:has-text("Continue")',
                'a:has-text("Accept")',
                'a:has-text("Agree")',
                '[role="button"]:has-text("Accept")',
                'button:has-text("قبول")',
                'button:has-text("موافق")',
            ]:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0 and await el.is_visible():
                        log.info(f"✅ لقيت: {sel}")
                        await el.click(force=True)
                        await human_delay(5, 7)
                        return True
                except Exception:
                    continue

            log.warning(f"ما لقيتش زر Accept (محاولة {attempt + 1})")
            await human_delay(3, 5)

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
