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
        self.user_id = None
        self.sender = None
        self.captcha_solved_count = 0

    async def login(self, username: str, password: str,
                    user_id: int = None, sender=None, context=None):
        self.username = username
        self.password = password
        self.user_id = user_id
        self.sender = sender

        page = await self.context.new_page()
        log.info("تسجيل الدخول...")
        await page.goto("https://console.cloud.google.com", wait_until="domcontentloaded")
        await human_delay(3, 5)
        await take_screenshot(page, "cc_01_loaded")
        log.info(f"URL: {page.url}")

        # ✅ حلقة: 8 محاولات
        for attempt in range(8):
            log.info(f"========== محاولة {attempt + 1} ==========")
            await human_delay(2, 3)
            await take_screenshot(page, f"cc_attempt_{attempt}")
            current_url = page.url
            log.info(f"URL: {current_url}")

            # ============================================
            # ✅ 1. أول حاجة: فحص CAPTCHA فـ أي صفحة
            # ============================================
            try:
                from automation.captcha_solver import has_captcha, detect_and_solve_captcha
                if await has_captcha(page):
                    if self.captcha_solved_count < 5:  # ✅ max 5 مرات
                        log.info(f"🚨 CAPTCHA detected ({self.captcha_solved_count + 1}/5)")
                        solution = await detect_and_solve_captcha(page)
                        if solution:
                            self.captcha_solved_count += 1
                            log.info(f"✅ CAPTCHA solved")
                            await human_delay(5, 8)
                            continue
                        else:
                            log.warning("⚠️ CAPTCHA ما تحلاش")
                            await human_delay(3, 5)
                            continue
                    else:
                        log.warning("⚠️ تجاوزنا حد CAPTCHA (5)")
            except Exception as e:
                log.warning(f"CAPTCHA check: {e}")

            # ============================================
            # ✅ 2. Dialog (Terms of Service)
            # ============================================
            if await self._handle_gcloud_dialog(page):
                log.info("✅ تم التعامل مع Dialog")
                await human_delay(5, 8)
                continue

            # ============================================
            # ✅ 3. Console ready?
            # ============================================
            if await self._is_console_ready(page):
                log.info("✅ وصلنا للـ Console!")
                await human_delay(3, 5)
                return page

            # ============================================
            # ✅ 4. Sign in?
            # ============================================
            if await self._is_signin_page(page):
                log.info("🔑 Sign in")
                try:
                    await self._do_signin(page, self.username, self.password)
                    await human_delay(5, 8)
                    await take_screenshot(page, f"cc_after_signin_{attempt}")
                except Exception as e:
                    log.warning(f"فشل sign in: {e}")
                    await human_delay(3, 5)
                continue

            # ============================================
            # ✅ 5. Verify?
            # ============================================
            if await self._has_verify_required(page):
                await take_screenshot(page, f"cc_verify_{attempt}")
                raise RuntimeError("❌ Google كتطلب verify")

            # ============================================
            # ✅ 6. كلمة سر غلط؟
            # ============================================
            if await self._has_wrong_password_error(page):
                await take_screenshot(page, f"cc_wrong_pwd_{attempt}")
                raise RuntimeError("❌ كلمة السر غلط")

            # ============================================
            # ✅ 7. TOS / Speedbump (تحقق إضافي)
            # ============================================
            if await self._is_tos_page(page):
                log.info("📋 TOS/Speedbump")
                clicked = await self._handle_tos_page(page)
                if clicked:
                    await human_delay(10, 15)
                    continue
                else:
                    await human_delay(5, 8)
                    continue

            # ============================================
            # ✅ 8. صفحة غير معروفة
            # ============================================
            log.warning(f"❓ صفحة غير معروفة: {current_url[:100]}")
            await human_delay(3, 5)

        await take_screenshot(page, "cc_final_fail")
        raise RuntimeError(f"❌ فشل بعد 8 محاولات\nURL: {page.url[:200]}")

    # ==================== TOS / Speedbump ====================

    async def _is_tos_page(self, page) -> bool:
        url = page.url.lower()
        if "workspacetermsofservice" in url or "speedbump" in url:
            return True
        try:
            text = (await page.inner_text("body")).lower()
            if "welcome to your new account" in text:
                return True
            if "terms of service" in text and "i understand" in text:
                return True
        except Exception:
            pass
        return False

    async def _handle_tos_page(self, page) -> bool:
        """يتعامل مع صفحة TOS/Speedbump"""
        await human_delay(5, 8)

        try:
            clicked = await page.evaluate("""
                async () => {
                    const sleep = (ms) => new Promise(r => setTimeout(r, ms));
                    const all = document.querySelectorAll('button, a, [role="button"]');
                    for (const el of all) {
                        if (el.offsetParent === null) continue;
                        if (el.disabled) continue;
                        const t = (el.innerText || el.value || '').trim().toLowerCase();
                        if (t === 'i understand' || t.includes('understand') ||
                            t === 'accept' || t === 'i agree' || t === 'agree') {
                            el.scrollIntoView({block: 'center'});
                            el.focus();
                            await sleep(300);
                            // ✅ 5 أحداث
                            el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
                            el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                            el.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }));
                            el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                            el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                            el.click();
                            return { clicked: t, tag: el.tagName };
                        }
                    }
                    return null;
                }
            """)
            if clicked:
                log.info(f"✅ TOS click: {clicked}")
                return True
        except Exception as e:
            log.warning(f"TOS: {e}")

        return False

    # ==================== Dialog (Terms of Service الجديد) ====================

    async def _handle_gcloud_dialog(self, page) -> bool:
        try:
            has_dialog = await page.evaluate("""
                () => {
                    const dialogs = document.querySelectorAll(
                        '[role="dialog"], .modal, [role="alertdialog"], mat-dialog-container'
                    );
                    for (const d of dialogs) {
                        if (d.offsetParent === null) continue;
                        const text = (d.innerText || '').toLowerCase();
                        if (text.includes('i agree') || text.includes('terms of service') ||
                            text.includes('welcome student')) {
                            return true;
                        }
                    }
                    const checkboxes = document.querySelectorAll('input[type="checkbox"]');
                    for (const cb of checkboxes) {
                        if (cb.offsetParent === null) continue;
                        return true;
                    }
                    return false;
                }
            """)

            if not has_dialog:
                return False

            log.info("🔍 لقيت Dialog — نضغط checkbox + Continue")

            # ✅ checkbox
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

            # ✅ Continue
            try:
                clicked_btn = await page.evaluate("""
                    async () => {
                        const sleep = (ms) => new Promise(r => setTimeout(r, ms));
                        const all = document.querySelectorAll('button, a, [role="button"], input[type="submit"]');
                        const keywords = ['continue', 'agree', 'accept', 'i agree', 'ok', 'yes'];
                        for (const el of all) {
                            if (el.offsetParent === null) continue;
                            if (el.disabled) continue;
                            const t = (el.innerText || el.value || '').trim().toLowerCase();
                            if (!t || t.length > 100) continue;
                            for (const kw of keywords) {
                                if (t === kw || t.includes(kw)) {
                                    el.scrollIntoView({block: 'center'});
                                    el.focus();
                                    await sleep(200);
                                    el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
                                    el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                                    el.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }));
                                    el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                                    el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                                    el.click();
                                    return { clicked: t.substring(0, 50) };
                                }
                            }
                        }
                        return null;
                    }
                """)
                if clicked_btn:
                    log.info(f"✅ Continue: {clicked_btn}")
                    await human_delay(5, 8)
                    return True
            except Exception as e:
                log.warning(f"Continue: {e}")

            return False
        except Exception as e:
            log.warning(f"Dialog: {e}")
            return False

    # ==================== Helpers ====================

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

    # ==================== Sign In ====================

    async def _do_signin(self, page, username: str, password: str):
        await take_screenshot(page, "cc_before_signin")

        # ========== EMAIL ==========
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
            raise RuntimeError("❌ فشل email")

        await self._click_next(page, "email")
        await human_delay(4, 6)
        await take_screenshot(page, "cc_after_email_next")

        # ✅ CAPTCHA بعد email
        try:
            from automation.captcha_solver import has_captcha, detect_and_solve_captcha
            if await has_captcha(page) and self.captcha_solved_count < 5:
                solution = await detect_and_solve_captcha(page)
                if solution:
                    self.captcha_solved_count += 1
                    log.info(f"✅ CAPTCHA after email ({self.captcha_solved_count}/5)")
                    await human_delay(5, 8)
        except Exception as e:
            log.warning(f"CAPTCHA بعد email: {e}")

        # ========== PASSWORD ==========
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
            except Exception as e:
                log.warning(f"فشل pwd {sel}: {e}")
                continue

        if not password_filled:
            await take_screenshot(page, "cc_no_pwd")
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
                    log.info(f"كليك على {sel} ({step})")
                    await el.click()
                    return
            except Exception:
                continue
