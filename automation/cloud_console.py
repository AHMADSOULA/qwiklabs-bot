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

        # ✅ حلقة كبيرة: 8 محاولات
        for attempt in range(8):
            log.info(f"========== محاولة {attempt + 1} ==========")
            await human_delay(2, 4)
            await take_screenshot(page, f"cc_attempt_{attempt}")
            current_url = page.url
            log.info(f"URL: {current_url}")

            # ========== 1. Console ready? ==========
            if await self._is_console_ready(page):
                log.info("✅ وصلنا للـ Console!")
                await self._wait_for_console(page, timeout=30000)
                return page

            # ========== 2. Welcome / TOS / Speedbump? ==========
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

            # ========== 3. Sign in? ==========
            if await self._is_signin_page(page):
                log.info("🔑 Sign in")

                # 3.1 نحل CAPTCHA أولاً (يدوياً)
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

                # 3.2 نسجلو (email + password)
                try:
                    await self._do_signin(page, self.username, self.password)
                    await human_delay(5, 8)
                    await take_screenshot(page, f"cc_after_signin_{attempt}")
                except Exception as e:
                    log.warning(f"فشل sign in: {e}")
                    await human_delay(3, 5)

                continue

            # ========== 4. Verify? ==========
            if await self._has_verify_required(page):
                await take_screenshot(page, f"cc_verify_{attempt}")
                raise RuntimeError("❌ Google كتطلب verify")

            # ========== 5. كلمة سر غلط؟ ==========
            if await self._has_wrong_password_error(page):
                await take_screenshot(page, f"cc_wrong_pwd_{attempt}")
                raise RuntimeError("❌ كلمة السر غلط")

            # ========== 6. صفحة غير معروفة ==========
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
        # ✅ Speedbump/TOS
        if "workspacetermsofservice" in url or "speedbump" in url:
            return True

        text = (await self._get_body_text(page)).lower()
        if "welcome to your new account" in text:
            return True
        if "terms of service" in text:
            return True

        # ✅ نفحصو واش كاين زر Accept
        try:
            for sel in [
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

        # ===== CAPTCHA بعد email =====
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

    # ==================== Welcome (8 طرق) ====================

    async def _handle_welcome_page(self, page, max_attempts: int = 3) -> bool:
        """
        يحاول يضغط على زر Accept بكل الطرق الممكنة.
        خاص لصفحة speedbump/workspacetermsofservice.
        """
        for attempt in range(max_attempts):
            await human_delay(3, 5)

            # ✅ 1. نسجل كل الأزرار الموجودة
            try:
                buttons_info = await page.evaluate("""
                    () => {
                        const all = document.querySelectorAll(
                            'button, a, [role="button"], input[type="submit"], input[type="button"]'
                        );
                        return Array.from(all).map((el, i) => ({
                            idx: i,
                            tag: el.tagName,
                            text: (el.innerText || el.value || el.textContent || '').trim().substring(0, 60),
                            type: el.type || '',
                            id: el.id || '',
                            cls: (el.className || '').toString().substring(0, 60),
                            visible: el.offsetParent !== null,
                            disabled: el.disabled || false,
                        }));
                    }
                """)
                log.info(f"🔍 الأزرار الموجودة: {buttons_info}")
            except Exception as e:
                log.warning(f"فشل جلب الأزرار: {e}")

            # ✅ 2. نسجل نص الصفحة
            try:
                body_text = await page.inner_text("body")
                body_text_short = body_text[:500].replace('\n', ' | ')
                log.info(f"📄 نص الصفحة: {body_text_short[:400]}")
            except Exception:
                pass

            # ✅ 3. نسجل الـ iframes
            try:
                iframes = await page.evaluate("""
                    () => {
                        const ifs = document.querySelectorAll('iframe');
                        return Array.from(ifs).map((f, i) => ({
                            idx: i,
                            src: (f.src || '').substring(0, 100),
                            visible: f.offsetParent !== null,
                        }));
                    }
                """)
                if iframes:
                    log.info(f"🔍 iframes: {iframes}")
            except Exception:
                pass

            # ✅ 4. JS click على كل زر فيه accept
            try:
                clicked = await page.evaluate("""
                    () => {
                        const all = document.querySelectorAll(
                            'button, a, [role="button"], input[type="submit"], input[type="button"], span, div'
                        );
                        const keywords = ['accept', 'agree', 'confirm', 'got it',
                                         'i agree', 'continue', 'ok', 'yes',
                                         'قبول', 'موافق', 'أوافق', 'متابعة'];
                        for (const el of all) {
                            if (el.offsetParent === null) continue;
                            const t = (el.innerText || el.value || el.textContent || '').trim().toLowerCase();
                            for (const kw of keywords) {
                                if (t === kw || t.includes(kw)) {
                                    el.click();
                                    return { clicked: el.innerText || el.value || 'clicked', tag: el.tagName };
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

            # ✅ 5. Playwright locators
            selectors = [
                'button:has-text("Accept")',
                'button:has-text("I agree")',
                'button:has-text("Agree")',
                'button:has-text("Confirm")',
                'button:has-text("Got it")',
                'button:has-text("Continue")',
                'button:has-text("OK")',
                'button:has-text("Yes")',
                'button:has-text("قبول")',
                'button:has-text("موافق")',
                'a:has-text("Accept")',
                'a:has-text("Agree")',
                '[role="button"]:has-text("Accept")',
                '[role="button"]:has-text("Agree")',
                'input[type="submit"]',
                'button[type="submit"]',
                'button:last-of-type',
                'input[value*="Accept" i]',
                'input[value*="Agree" i]',
            ]
            for sel in selectors:
                try:
                    el = page.locator(sel).first
                    if await el.count() == 0:
                        continue
                    try:
                        if not await el.is_visible():
                            continue
                    except Exception:
                        pass
                    log.info(f"✅ كليك {sel}")
                    await el.click(force=True, timeout=5000)
                    await human_delay(5, 8)
                    return True
                except Exception as e:
                    log.warning(f"{sel}: {e}")
                    continue

            # ✅ 6. Blue button (Google)
            try:
                clicked = await page.evaluate("""
                    () => {
                        const all = document.querySelectorAll('button, input[type="submit"], a');
                        for (const el of all) {
                            if (el.offsetParent === null) continue;
                            const bg = window.getComputedStyle(el).backgroundColor;
                            if (bg === 'rgb(26, 115, 232)' || bg === 'rgb(66, 133, 244)' ||
                                bg === 'rgb(23, 78, 166)' || bg === 'rgb(21, 101, 192)') {
                                el.click();
                                return el.innerText || 'blue';
                            }
                        }
                        return null;
                    }
                """)
                if clicked:
                    log.info(f"✅ blue button: {clicked}")
                    await human_delay(5, 8)
                    return True
            except Exception:
                pass

            # ✅ 7. آخر زر فـ الصفحة
            try:
                result = await page.evaluate("""
                    () => {
                        const all = document.querySelectorAll('button, input[type="submit"]');
                        const visible = Array.from(all).filter(b => b.offsetParent !== null);
                        if (visible.length > 0) {
                            const last = visible[visible.length - 1];
                            last.click();
                            return { clicked: 'last', text: last.innerText || last.value };
                        }
                        return null;
                    }
                """)
                if result:
                    log.info(f"✅ last button: {result}")
                    await human_delay(5, 8)
                    return True
            except Exception:
                pass

            # ✅ 8. Scroll + Tab + Enter
            try:
                await page.keyboard.press("End")
                await human_delay(1, 2)
                await page.keyboard.press("Tab")
                await human_delay(0.5, 1)
                await page.keyboard.press("Enter")
                await human_delay(4, 6)
                log.info("✅ Scroll + Tab + Enter")
                return True
            except Exception:
                pass

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
