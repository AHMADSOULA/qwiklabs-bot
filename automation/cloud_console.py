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

            # 1. Console ready?
            if await self._is_console_ready(page):
                log.info("✅ وصلنا للـ Console!")
                await self._wait_for_console(page, timeout=30000)
                return page

            # 2. Welcome / TOS / Speedbump?
            if await self._is_welcome_page(page):
                log.info("📋 Welcome/TOS/Speedbump — نحاول Accept")
                clicked = await self._handle_welcome_page(page)
                if clicked:
                    await human_delay(5, 8)
                    continue
                else:
                    log.warning("⚠️ ما لقيتش Accept — نستنى ونعاود")
                    await human_delay(4, 6)
                    continue

            # 3. Sign in?
            if await self._is_signin_page(page):
                log.info("🔑 Sign in")

                # 3.1 CAPTCHA يدوياً
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

                # 3.2 تسجيل
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
            await human_delay(4, 6)

        await take_screenshot(page, "cc_final_fail")
        raise RuntimeError(f"❌ فشل بعد 8 محاولات\nURL: {page.url[:200]}")

    # ==================== CAPTCHA ====================

    async def _fill_captcha(self, page, solution: str):
        """يكتب الحل فـ حقل CAPTCHA"""
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
        if "terms of service" in text:
            return True

        try:
            for sel in [
                'button:has-text("I understand")',
                'button:has-text("Accept")',
                'button:has-text("I agree")',
                'button:has-text("Agree")',
                'button:has-text("Confirm")',
                'button:has-text("Got it")',
                'button:has-text("Continue")',
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

        # EMAIL
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

        # CAPTCHA بعد email
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

        # PASSWORD
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

    # ==================== Welcome (محسّن) ====================

    async def _handle_welcome_page(self, page, max_attempts: int = 3) -> bool:
        """
        يحاول يضغط على زر Accept بكل الطرق.
        خاص لصفحة speedbump/workspacetermsofservice (Qwiklabs).
        """
        for attempt in range(max_attempts):
            await human_delay(3, 5)

            # ✅ 1. تسجيل الأزرار
            try:
                buttons_info = await page.evaluate("""
                    () => {
                        const all = document.querySelectorAll(
                            'button, a, [role="button"], input[type="submit"], input[type="button"]'
                        );
                        return Array.from(all).map((el, i) => ({
                            idx: i,
                            tag: el.tagName,
                            text: (el.innerText || el.value || el.textContent || '').trim().substring(0, 80),
                            type: el.type || '',
                            cls: (el.className || '').toString().substring(0, 60),
                            visible: el.offsetParent !== null,
                            disabled: el.disabled || false,
                        }));
                    }
                """)
                log.info(f"🔍 الأزرار: {buttons_info}")
            except Exception as e:
                log.warning(f"فشل جلب الأزرار: {e}")

            # ✅ 2. JS multi-click قوي
            try:
                clicked = await page.evaluate("""
                    async () => {
                        const sleep = (ms) => new Promise(r => setTimeout(r, ms));

                        function findButton() {
                            const all = document.querySelectorAll('button, a, [role="button"]');
                            const exactTexts = ['i understand', 'i agree', 'i accept',
                                              'accept', 'agree', 'confirm', 'got it',
                                              'continue', 'ok', 'yes',
                                              'أفهم', 'قبول', 'موافق'];
                            for (const el of all) {
                                if (el.offsetParent === null) continue;
                                if (el.disabled) continue;
                                const rawText = (el.innerText || el.value || el.textContent || '').trim();
                                if (!rawText || rawText.length > 100) continue;
                                const t = rawText.toLowerCase();
                                for (const kw of exactTexts) {
                                    if (t === kw) return el;
                                }
                            }
                            for (const el of all) {
                                if (el.offsetParent === null) continue;
                                if (el.disabled) continue;
                                const rawText = (el.innerText || el.value || el.textContent || '').trim();
                                if (!rawText || rawText.length > 100) continue;
                                const t = rawText.toLowerCase();
                                if (t.includes('understand') || t.includes('accept') ||
                                    t.includes('agree') || t.includes('continue') ||
                                    t.includes('got it') || t.includes('confirm')) {
                                    return el;
                                }
                            }
                            const submits = document.querySelectorAll('button[type="submit"], input[type="submit"]');
                            for (const el of submits) {
                                if (el.offsetParent === null) continue;
                                if (el.disabled) continue;
                                const rawText = (el.innerText || el.value || '').trim();
                                if (rawText.length < 100) return el;
                            }
                            return null;
                        }

                        const btn = findButton();
                        if (!btn) return { error: 'not_found' };

                        const text = (btn.innerText || btn.value || '').trim();

                        // محاولة 1
                        btn.scrollIntoView({block: 'center'});
                        await sleep(300);
                        btn.click();
                        await sleep(1000);

                        // محاولة 2
                        btn.dispatchEvent(new MouseEvent('click', {
                            bubbles: true, cancelable: true, view: window
                        }));
                        await sleep(500);

                        // محاولة 3
                        btn.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
                        btn.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }));
                        await sleep(500);

                        // محاولة 4
                        if (btn.parentElement) {
                            btn.parentElement.dispatchEvent(new MouseEvent('click', {
                                bubbles: true, cancelable: true, view: window
                            }));
                        }
                        await sleep(500);

                        // محاولة 5
                        const form = btn.closest('form');
                        if (form) {
                            try { form.submit(); } catch(e) {}
                        }

                        return {
                            clicked: text,
                            tag: btn.tagName,
                            method: 'multi_click',
                            form: form ? 'yes' : 'no',
                        };
                    }
                """)
                if clicked and clicked.get("clicked"):
                    log.info(f"✅ JS multi-click: {clicked}")
                    await human_delay(6, 10)

                    new_url = page.url.lower()
                    if "workspacetermsofservice" not in new_url and "speedbump" not in new_url:
                        log.info(f"🎉 خرجنا من TOS! URL: {page.url}")
                        return True
                    else:
                        log.warning(f"⚠️ مازال فـ TOS")
                        continue
                elif clicked and clicked.get("error"):
                    log.warning(f"⚠️ JS: {clicked['error']}")
            except Exception as e:
                log.warning(f"JS: {e}")

            # ✅ 3. Playwright click
            for sel in [
                'button:has-text("I understand")',
                'button:has-text("I agree")',
                'button:has-text("Accept")',
                'button[type="submit"]',
                '.VfPpkd-LgbsSe-OWXEXe-k8QpJ',
            ]:
                try:
                    el = page.locator(sel).first
                    if await el.count() == 0:
                        continue
                    if not await el.is_visible():
                        continue
                    if await el.is_disabled():
                        continue

                    log.info(f"✅ Playwright click: {sel}")
                    try:
                        await el.click(timeout=3000)
                    except Exception:
                        try:
                            await el.click(force=True, timeout=3000)
                        except Exception:
                            try:
                                await el.dispatch_event("click")
                            except Exception:
                                pass

                    await human_delay(6, 10)
                    new_url = page.url.lower()
                    if "workspacetermsofservice" not in new_url and "speedbump" not in new_url:
                        log.info(f"🎉 خرجنا من TOS!")
                        return True
                except Exception as e:
                    log.warning(f"{sel}: {e}")
                    continue

            log.warning(f"⚠️ ما لقيتش Accept (محاولة {attempt + 1})")
            await human_delay(3, 5)

        return False

    # ==================== Console Ready ====================

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
