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
        self.tos_clicked = False
        self.dialog_handled = False

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

        for attempt in range(8):
            log.info(f"========== محاولة {attempt + 1} ==========")
            await human_delay(2, 4)
            await take_screenshot(page, f"cc_attempt_{attempt}")
            current_url = page.url
            log.info(f"URL: {current_url}")

            # ✅ 0. Dialog الجديد (Terms of Service) — قبل كل شي
            if await self._handle_gcloud_dialog(page):
                log.info("✅ تم التعامل مع Dialog")
                await human_delay(5, 8)
                continue

            # 1. Console ready?
            if await self._is_console_ready(page):
                log.info("✅ وصلنا للـ Console!")
                await self._wait_for_console(page, timeout=30000)
                return page

            # 2. Welcome / TOS / Speedbump?
            if await self._is_welcome_page(page):
                log.info("📋 Welcome/TOS/Speedbump")

                if self.tos_clicked:
                    log.info("⏳ ضغطنا قبل على Accept — نستنى Google تكمل...")
                    await human_delay(10, 15)
                    new_url = page.url.lower()
                    if "workspacetermsofservice" not in new_url and "speedbump" not in new_url:
                        log.info("🎉 خرجنا من TOS بعد الانتظار!")
                        self.tos_clicked = False
                        continue
                    else:
                        log.warning("⚠️ مازال فـ TOS")
                        await human_delay(10, 15)
                        continue
                else:
                    log.info("🖱️ نضغط على Accept مرة وحدة فقط...")
                    clicked = await self._handle_welcome_page_once(page)
                    if clicked:
                        self.tos_clicked = True
                        log.info("✅ ضغطنا — نستنى Google تكمل...")
                        await human_delay(10, 15)
                        continue
                    else:
                        log.warning("⚠️ ما لقيتش Accept")
                        await human_delay(5, 8)
                        continue

            # 3. Sign in?
            if await self._is_signin_page(page):
                log.info("🔑 Sign in")
                try:
                    from automation.captcha_solver import detect_and_solve_captcha
                    await human_delay(1, 2)
                    solution = await detect_and_solve_captcha(
                        page,
                        user_id=self.user_id,
                        sender=self.sender,
                        context=None,
                    )
                    if solution:
                        log.info(f"✅ CAPTCHA solved: {solution}")
                        await self._fill_captcha(page, solution)
                        await human_delay(4, 6)
                        await take_screenshot(page, f"cc_after_captcha_{attempt}")
                        continue
                except Exception as e:
                    log.warning(f"فشل CAPTCHA: {e}")

                try:
                    await self._do_signin(page, self.username, self.password)
                    await human_delay(5, 8)
                    await take_screenshot(page, f"cc_after_signin_{attempt}")
                except Exception as e:
                    log.warning(f"فشل sign in: {e}")
                    await human_delay(3, 5)
                continue

            # 4. Verify?
            if await self._has_verify_required(page):
                await take_screenshot(page, f"cc_verify_{attempt}")
                raise RuntimeError("❌ Google كتطلب verify")

            # 5. كلمة سر غلط؟
            if await self._has_wrong_password_error(page):
                await take_screenshot(page, f"cc_wrong_pwd_{attempt}")
                raise RuntimeError("❌ كلمة السر غلط")

            # 6. صفحة غير معروفة
            log.warning(f"❓ صفحة غير معروفة: {current_url[:100]}")
            await human_delay(5, 8)

        await take_screenshot(page, "cc_final_fail")
        raise RuntimeError(f"❌ فشل بعد 8 محاولات\nURL: {page.url[:200]}")

    # ==================== Dialog جديد (Terms of Service) ====================

    async def _handle_gcloud_dialog(self, page) -> bool:
        """
        يتعامل مع Dialog Terms of Service الجديد.
        - يضغط على checkbox
        - يضغط على Continue
        """
        try:
            # ✅ نفحص واش كاين Dialog
            has_dialog = await page.evaluate("""
                () => {
                    // نلقاو dialogs
                    const dialogs = document.querySelectorAll(
                        '[role="dialog"], .modal, [role="alertdialog"], .VfPpkd-P5VOMc, mat-dialog-container'
                    );
                    for (const d of dialogs) {
                        if (d.offsetParent === null) continue;
                        const text = (d.innerText || '').toLowerCase();
                        if (text.includes('i agree') || text.includes('terms of service') ||
                            text.includes('agree to the google cloud') ||
                            text.includes('welcome student') ||
                            text.includes('continue')) {
                            return true;
                        }
                    }
                    // ✅ نتحققو من وجود checkbox
                    const checkboxes = document.querySelectorAll('input[type="checkbox"]');
                    for (const cb of checkboxes) {
                        if (cb.offsetParent === null) continue;
                        return true;
                    }
                    // ✅ نتحققو من زر "Continue"
                    const all = document.querySelectorAll('button, a, [role="button"]');
                    for (const el of all) {
                        if (el.offsetParent === null) continue;
                        const t = (el.innerText || '').trim().toLowerCase();
                        if (t === 'continue' || t === 'agree and continue' ||
                            t === 'i agree' || t === 'accept') {
                            // نتأكدو بلي ماشي زر عام
                            const parentText = (el.closest('[role="dialog"], .modal, [role="alertdialog"]')?.innerText || '').toLowerCase();
                            if (parentText.includes('terms of service') ||
                                parentText.includes('i agree') ||
                                parentText.includes('welcome student')) {
                                return true;
                            }
                        }
                    }
                    return false;
                }
            """)

            if not has_dialog:
                return False

            log.info("🔍 لقيت Dialog — نحاول نضغط checkbox + Continue")

            # ✅ 1. نضغطو على checkbox
            try:
                clicked_cb = await page.evaluate("""
                    () => {
                        const checkboxes = document.querySelectorAll('input[type="checkbox"]');
                        for (const cb of checkboxes) {
                            if (cb.offsetParent === null) continue;
                            if (cb.checked) continue;  // واش checked already
                            // نلقاو الـ label الأب
                            const label = cb.closest('label');
                            if (label) {
                                label.click();
                            } else {
                                cb.click();
                            }
                            cb.dispatchEvent(new Event('change', { bubbles: true }));
                            return {
                                name: cb.name || '',
                                id: cb.id || '',
                                checked: cb.checked,
                            };
                        }
                        return null;
                    }
                """)
                if clicked_cb:
                    log.info(f"✅ ضغطنا على checkbox: {clicked_cb}")
                    await human_delay(1, 2)
            except Exception as e:
                log.warning(f"فشل checkbox: {e}")

            # ✅ 2. نضغطو على Continue
            try:
                clicked_btn = await page.evaluate("""
                    () => {
                        const all = document.querySelectorAll('button, a, [role="button"]');
                        const keywords = ['continue', 'agree', 'accept', 'i agree',
                                        'agree and continue', 'submit', 'ok', 'yes'];
                        for (const el of all) {
                            if (el.offsetParent === null) continue;
                            if (el.disabled) continue;
                            const t = (el.innerText || el.value || '').trim().toLowerCase();
                            if (!t || t.length > 100) continue;
                            for (const kw of keywords) {
                                if (t === kw || t.includes(kw)) {
                                    el.scrollIntoView({block: 'center'});
                                    el.focus();
                                    el.click();
                                    return {
                                        clicked: t.substring(0, 50),
                                        tag: el.tagName,
                                        cls: (el.className || '').toString().substring(0, 60),
                                    };
                                }
                            }
                        }
                        return null;
                    }
                """)
                if clicked_btn:
                    log.info(f"✅ ضغطنا على Continue: {clicked_btn}")
                    await human_delay(3, 5)
                    return True
            except Exception as e:
                log.warning(f"فشل Continue: {e}")

            # ✅ 3. Playwright click احتياطي
            for sel in [
                'button:has-text("Continue")',
                'button:has-text("Agree and continue")',
                'button:has-text("I agree")',
                'button:has-text("Accept")',
                '[role="dialog"] button:has-text("Continue")',
                'mat-dialog-container button:has-text("Continue")',
            ]:
                try:
                    el = page.locator(sel).first
                    if await el.count() == 0:
                        continue
                    if not await el.is_visible():
                        continue
                    log.info(f"✅ Playwright: {sel}")
                    await el.click(timeout=5000)
                    await human_delay(3, 5)
                    return True
                except Exception:
                    continue

            return False
        except Exception as e:
            log.warning(f"فشل Dialog: {e}")
            return False

    # ==================== CAPTCHA ====================

    async def _fill_captcha(self, page, solution: str):
        for sel in [
            'input[name="ca"]',
            'input[id="ca"]',
            'input[name="captcha"]',
            'input[type="text"][aria-label*="Type the text" i]',
            'input[type="text"][aria-label*="characters" i]',
            'input[type="text"]',
        ]:
            try:
                inp = page.locator(sel).first
                if await inp.count() == 0 or not await inp.is_visible():
                    continue
                name = (await inp.get_attribute("name") or "").lower()
                id_attr = (await inp.get_attribute("id") or "").lower()
                if "email" in name or "identifier" in id_attr:
                    continue

                log.info(f"✅ حقل CAPTCHA: {sel}")
                await inp.click()
                await human_delay(0.3, 0.6)
                await inp.fill("")
                await human_delay(0.2, 0.4)
                await inp.fill(solution)
                await human_delay(0.5, 1.0)

                val = await inp.input_value()
                if val.strip():
                    log.info(f"✍️ كتبت: {val}")
                    for btn_sel in [
                        '#captchaNext',
                        'button:has-text("Next")',
                        'input[type="submit"]',
                        'button[type="submit"]',
                        '#identifierNext',
                    ]:
                        try:
                            btn = page.locator(btn_sel).first
                            if await btn.count() > 0 and await btn.is_visible():
                                await btn.click()
                                await human_delay(3, 5)
                                return True
                        except Exception:
                            continue
                    return True
            except Exception as e:
                log.warning(f"فشل {sel}: {e}")
                continue
        return False

    # ==================== Helpers ====================

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
        if "terms of service" in text and "i understand" in text:
            return True

        try:
            for sel in [
                'button:has-text("I understand")',
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

        try:
            from automation.captcha_solver import detect_and_solve_captcha
            await human_delay(1, 2)
            solution = await detect_and_solve_captcha(
                page,
                user_id=self.user_id,
                sender=self.sender,
                context=None,
            )
            if solution:
                log.info(f"✅ CAPTCHA solved (after email)")
                await self._fill_captcha(page, solution)
                await human_delay(4, 6)
        except Exception as e:
            log.warning(f"فشل CAPTCHA: {e}")

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

    async def _handle_welcome_page_once(self, page) -> bool:
        await human_delay(3, 5)
        try:
            clicked = await page.evaluate("""
                () => {
                    const exactTexts = ['i understand', 'i agree', 'i accept',
                                      'accept', 'agree', 'confirm', 'got it',
                                      'continue', 'ok', 'yes'];
                    const all = document.querySelectorAll('button, a, [role="button"]');
                    for (const el of all) {
                        if (el.offsetParent === null) continue;
                        if (el.disabled) continue;
                        const rawText = (el.innerText || el.value || el.textContent || '').trim();
                        if (!rawText || rawText.length > 100) continue;
                        const t = rawText.toLowerCase();
                        for (const kw of exactTexts) {
                            if (t === kw) {
                                el.scrollIntoView({block: 'center'});
                                el.focus();
                                el.click();
                                return { clicked: rawText, tag: el.tagName };
                            }
                        }
                    }
                    return null;
                }
            """)
            if clicked:
                log.info(f"✅ كليك مرة وحدة: {clicked}")
                return True
        except Exception as e:
            log.warning(f"JS: {e}")

        for sel in [
            'button:has-text("I understand")',
            'button:has-text("Accept")',
            'button[type="submit"]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() == 0:
                    continue
                if not await el.is_visible():
                    continue
                log.info(f"✅ Playwright: {sel}")
                await el.click(timeout=5000)
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
            log.warning("Timeout Console")
        await human_delay(3, 5)
        await take_screenshot(page, "cc_console_ready")
