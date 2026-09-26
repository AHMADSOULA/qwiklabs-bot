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
            for attempt in range(3):
                log.info(f"--- محاولة {attempt + 1} ---")
                await self._wait_for_login_or_console(page)

                # 🔍 فحص: كلمة سر غلط؟
                if await self._has_wrong_password_error(page):
                    log.warning("⚠️ كلمة السر غلط!")
                    await take_screenshot(page, f"cc_wrong_pwd_{attempt}")
                    raise RuntimeError(
                        "❌ كلمة السر غير صحيحة.\nجدد الرابط من Skills."
                    )

                # 🔍 فحص: verify phone?
                if await self._has_verify_required(page):
                    log.warning("⚠️ Google كتطلب verify phone/email")
                    await take_screenshot(page, f"cc_verify_{attempt}")
                    raise RuntimeError(
                        "❌ Google كتطلب التحقق من الهاتف.\n"
                        "سجل يدوياً أول مرة."
                    )

                # 1. إذا كانت Sign in → سجل
                if await self._is_signin_page(page):
                    log.info(f"صفحة Sign in (محاولة {attempt + 1})")
                    await self._do_signin(page, self.username, self.password)
                    await human_delay(5, 7)
                    await take_screenshot(page, f"cc_after_signin_{attempt}")

                # 2. Welcome / TOS / new
                if "welcome" in page.url.lower() or "/new" in page.url.lower():
                    log.info("📋 صفحة Welcome/TOS")
                    await self._handle_welcome_page(page)
                    await human_delay(8, 12)

                # 3. Welcome (عام)
                await self._handle_welcome_page(page)
                await human_delay(4, 6)

                # 4. Console?
                if await self._is_console_ready(page):
                    log.info(f"✅ وصلنا للـ Console")
                    break

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
        try:
            content = (await page.content()).lower()
            for txt in ['incorrect password', 'wrong password',
                        'كلمة السر غير صحيحة']:
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
        """✅ بلا /welcome — باش نعالجو TOS"""
        url = page.url
        if "console.cloud.google.com" not in url:
            return False
        if "signin" in url.lower() or "accounts.google.com" in url:
            return False
        if "/welcome" in url.lower() or "/new" in url.lower():
            return False
        if "project=" in url:
            return True
        if "/home/" in url:
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

    # ==========================================
    # 🔐 تسجيل الدخول
    # ==========================================

    async def _do_signin(self, page, username: str, password: str):
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
                    log.info(f"✅ طريقة 1 نجحت")
                    email_filled = True
                    break

                log.warning("fill ما خدمش — نجرب type")
                await el.click()
                await human_delay(0.3, 0.5)
                await page.keyboard.type(username, delay=50)
                await human_delay(0.3, 0.8)

                val = await el.input_value()
                if val.strip():
                    log.info(f"✅ طريقة 2 نجحت")
                    email_filled = True
                    break

                log.warning("type ما خدمش — نجرب JS")
                await page.evaluate(
                    """(args) => {
                        const inputs = document.querySelectorAll('input');
                        for (const inp of inputs) {
                            if (inp.type === 'email' || inp.type === 'text' ||
                                inp.name === 'identifier' || inp.id === 'identifierId') {
                                inp.focus();
                                inp.value = args.val;
                                inp.dispatchEvent(new Event('input', { bubbles: true }));
                                inp.dispatchEvent(new Event('change', { bubbles: true }));
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
                    log.info(f"✅ طريقة 3 نجحت")
                    email_filled = True
                    break

            except Exception as e:
                log.warning(f"فشل مع {sel}: {e}")
                continue

        if not email_filled:
            await take_screenshot(page, "cc_email_not_filled")
            raise RuntimeError("ما قدرتش نكتب الإيميل")

        # ===== Next =====
        await human_delay(0.5, 1.2)
        await self._click_next(page, "email")
        await human_delay(3, 5)

        # ========== 🔍 CAPTCHA ==========
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
                log.info("✅ تم حل CAPTCHA")
                await human_delay(4, 6)
                await take_screenshot(page, "cc_after_captcha")
        except Exception as e:
            log.warning(f"فشل حل CAPTCHA: {e}")

        # ========== Password ==========
        password_filled = False
        password_selectors = [
            'input[type="password"]',
            'input[name="password"]',
            'input[autocomplete="current-password"]',
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
                    log.info(f"✅ كلمة السر (طريقة 1)")
                    password_filled = True
                    break

                log.warning("fill ما خدمش — type")
                await el.click()
                await human_delay(0.3, 0.5)
                await page.keyboard.type(password, delay=50)
                await human_delay(0.3, 0.8)

                val = await el.input_value()
                if val.strip():
                    log.info(f"✅ كلمة السر (طريقة 2)")
                    password_filled = True
                    break

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
                    log.info(f"✅ كلمة السر (طريقة 3)")
                    password_filled = True
                    break

            except Exception as e:
                log.warning(f"فشل كلمة السر مع {sel}: {e}")
                continue

        if not password_filled:
            await take_screenshot(page, "cc_pwd_not_filled")
            raise RuntimeError("ما قدرتش نكتب كلمة السر")

        # ===== Next =====
        await human_delay(0.5, 1.2)
        await self._click_next(page, "password")
        await human_delay(4, 7)

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

    # ==========================================
    # ✅ Welcome / TOS — checkbox + Agree
    # ==========================================

    async def _handle_welcome_page(self, page, max_attempts: int = 3) -> bool:
        """
        يتعامل مع صفحة Welcome/TOS:
        1. يضغط checkbox (☐ I agree...)
        2. يضغط زر Agree and continue / I understand / Accept
        """
        for attempt in range(max_attempts):
            await human_delay(3, 5)

            # ✅ 1. نضغط على checkbox
            try:
                clicked_cb = await page.evaluate("""
                    () => {
                        const checkboxes = document.querySelectorAll('input[type="checkbox"]');
                        for (const cb of checkboxes) {
                            if (cb.offsetParent === null) continue;
                            if (cb.checked) return { already: true };
                            cb.scrollIntoView({block: 'center'});
                            cb.focus();
                            const label = cb.closest('label');
                            if (label) label.click();
                            else cb.click();
                            cb.dispatchEvent(new Event('change', { bubbles: true }));
                            cb.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                            return { checked: cb.checked };
                        }
                        return null;
                    }
                """)
                if clicked_cb:
                    log.info(f"✅ checkbox: {clicked_cb}")
                    await human_delay(1, 2)
            except Exception as e:
                log.warning(f"checkbox: {e}")

            # ✅ 2. نضغط الزر
            try:
                clicked = await page.evaluate("""
                    () => {
                        const all = document.querySelectorAll(
                            'button, a, [role="button"], input[type="submit"]'
                        );
                        const keywords = [
                            'agree and continue', 'i agree', 'i understand',
                            'understand', 'accept', 'agree', 'continue', 'got it'
                        ];
                        for (const el of all) {
                            if (el.offsetParent === null) continue;
                            if (el.disabled) continue;
                            const text = (el.innerText || el.value || '').trim().toLowerCase();
                            if (!text || text.length > 100) continue;
                            for (const kw of keywords) {
                                if (text.includes(kw)) {
                                    el.scrollIntoView({block: 'center'});
                                    el.focus();
                                    el.click();
                                    return text;
                                }
                            }
                        }
                        return null;
                    }
                """)
                if clicked:
                    log.info(f"✅ ضغط على: {clicked}")
                    await human_delay(5, 8)
                    return True
            except Exception as e:
                log.warning(f"JS click: {e}")

            # ✅ 3. Playwright locators
            for sel in [
                'button:has-text("Agree and continue")',
                'button:has-text("I understand")',
                'button:has-text("I agree")',
                'button:has-text("Accept")',
                'button:has-text("Agree")',
                'button:has-text("Continue")',
            ]:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0 and await el.is_visible():
                        log.info(f"✅ Playwright: {sel}")
                        await el.click(force=True)
                        await human_delay(5, 8)
                        return True
                except Exception:
                    continue

        return False

    # ==========================================
    # ✅ انتظار Console
    # ==========================================

    async def _wait_for_console(self, page, timeout: int = 30000):
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

        # ✅ نستنو 5 ثواني إضافية
        await human_delay(5, 8)

        # ✅ Screenshot مع timeout قصير
        try:
            import time
            path = f"/app/data/screenshots/{int(time.time())}_cc_ready.png"
            await page.screenshot(path=path, full_page=False, timeout=15000)
            log.info(f"📸 {path}")
        except Exception as e:
            log.warning(f"فشل screenshot: {e}")
