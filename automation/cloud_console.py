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
        self.welcome_clicked = False
        self.captcha_solved = 0

    async def login(self, username: str, password: str,
                    user_id: int = None, sender=None, context=None):
        self.username = username
        self.password = password
        self.user_id = user_id
        self.sender = sender

        page = await self.context.new_page()
        log.info("تسجيل الدخول...")

        # ✅ انتظار طويل قبل البدء
        await page.goto("https://console.cloud.google.com", wait_until="domcontentloaded")
        log.info("⏳ نستنى 8s باش الصفحة تكمل...")
        await human_delay(8, 12)
        await take_screenshot(page, "cc_01_loaded")
        log.info(f"URL: {page.url}")

        try:
            for attempt in range(6):
                log.info(f"========== محاولة {attempt + 1} ==========")
                await human_delay(3, 5)
                await take_screenshot(page, f"cc_attempt_{attempt}")
                log.info(f"URL: {page.url}")

                # ============================================
                # ✅ 1. Console ready?
                # ============================================
                if await self._is_console_ready(page):
                    log.info("✅ وصلنا للـ Console!")
                    await human_delay(5, 8)
                    return page

                # ============================================
                # ✅ 2. Welcome / TOS / Speedbump
                # ============================================
                if await self._is_welcome_page(page):
                    log.info("📋 Welcome/TOS/Speedbump")
                    log.info("⏳ نستنى 8s باش الصفحة تكمل...")
                    await human_delay(8, 12)

                    # ✅ نضغط Accept
                    log.info("🖱️ نضغط على Accept...")
                    clicked = await self._handle_welcome_hard(page)
                    if clicked:
                        self.welcome_clicked = True
                        log.info("✅ ضغطنا — نستنى 15s")
                        await human_delay(15, 20)
                    else:
                        log.warning("⚠️ ما لقيناش Accept")
                        await human_delay(5, 8)
                    continue

                # ============================================
                # ✅ 3. CAPTCHA (فحص + حل)
                # ============================================
                try:
                    from automation.captcha_solver import detect_and_solve_captcha
                    solution = await detect_and_solve_captcha(
                        page,
                        user_id=user_id,
                        sender=sender,
                        context=context,
                    )
                    if solution:
                        log.info(f"✅ CAPTCHA solved: {solution}")
                        await self._fill_captcha(page, solution)
                        log.info("⏳ نستنى 8s بعد CAPTCHA...")
                        await human_delay(8, 12)
                        continue
                except Exception as e:
                    log.warning(f"CAPTCHA: {e}")

                # ============================================
                # ✅ 4. Sign in?
                # ============================================
                if await self._is_signin_page(page):
                    log.info("🔑 Sign in")
                    log.info("⏳ نستنى 5s باش الصفحة تكمل...")
                    await human_delay(5, 8)

                    try:
                        await self._do_signin(page, self.username, self.password)
                        log.info("⏳ نستنى 10s بعد sign in...")
                        await human_delay(10, 15)
                        await take_screenshot(page, f"cc_after_signin_{attempt}")
                    except Exception as e:
                        log.warning(f"فشل sign in: {e}")
                        await human_delay(5, 8)
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
                # ✅ 7. صفحة غير معروفة — نستنى
                # ============================================
                log.warning(f"❓ صفحة غير معروفة: {page.url[:100]}")
                log.info("⏳ نستنى 10s...")
                await human_delay(10, 15)

            await take_screenshot(page, "cc_final_fail")
            raise RuntimeError(f"❌ فشل بعد 6 محاولات\nURL: {page.url[:200]}")

        except Exception as e:
            log.error(f"فشل: {e}")
            await take_screenshot(page, "cc_error")
            raise

    # ==================== Welcome Hard Click ====================

    async def _handle_welcome_hard(self, page) -> bool:
        """يضغط على Accept بـ 5 طرق"""
        await human_delay(3, 5)

        # ✅ نسجل الأزرار
        try:
            buttons = await page.evaluate("""
                () => {
                    const all = document.querySelectorAll('button, a, [role="button"]');
                    return Array.from(all).map((el, i) => ({
                        idx: i,
                        tag: el.tagName,
                        text: (el.innerText || el.value || '').trim().substring(0, 60),
                        visible: el.offsetParent !== null,
                        disabled: el.disabled || false,
                    })).filter(b => b.visible && !b.disabled && b.text);
                }
            """)
            log.info(f"🔍 الأزرار: {buttons}")
        except Exception:
            pass

        # ✅ 1. JS click (5 أحداث)
        try:
            clicked = await page.evaluate("""
                async () => {
                    const sleep = (ms) => new Promise(r => setTimeout(r, ms));
                    function findBtn() {
                        const all = document.querySelectorAll('button, a, [role="button"]');
                        // exact
                        for (const el of all) {
                            if (el.offsetParent === null) continue;
                            if (el.disabled) continue;
                            const t = (el.innerText || el.value || '').trim().toLowerCase();
                            if (t === 'accept' || t === 'i understand' || t === 'i agree' ||
                                t === 'agree' || t === 'continue') return el;
                        }
                        // includes
                        for (const el of all) {
                            if (el.offsetParent === null) continue;
                            if (el.disabled) continue;
                            const t = (el.innerText || el.value || '').trim().toLowerCase();
                            if (t.includes('accept') || t.includes('understand') ||
                                t.includes('agree')) return el;
                        }
                        return null;
                    }
                    const btn = findBtn();
                    if (!btn) return { error: 'not_found' };
                    const text = (btn.innerText || btn.value || '').trim();
                    btn.scrollIntoView({block: 'center'});
                    btn.focus();
                    await sleep(300);
                    btn.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
                    btn.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                    btn.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }));
                    btn.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                    btn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                    btn.click();
                    return { clicked: text, tag: btn.tagName };
                }
            """)
            if clicked and clicked.get("clicked"):
                log.info(f"✅ JS 5-event: {clicked}")
                return True
        except Exception as e:
            log.warning(f"JS: {e}")

        # ✅ 2. Playwright
        for sel in [
            'button:has-text("Accept")',
            'button:has-text("I understand")',
            'button:has-text("I agree")',
            'button:has-text("Agree")',
            'button:has-text("Continue")',
            'button[type="submit"]',
            '[role="button"]:has-text("Accept")',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() == 0:
                    continue
                if not await el.is_visible():
                    continue
                log.info(f"✅ Playwright: {sel}")
                try:
                    await el.click(timeout=3000)
                    return True
                except Exception:
                    try:
                        await el.click(force=True, timeout=3000)
                        return True
                    except Exception:
                        pass
            except Exception:
                continue

        # ✅ 3. Blue button
        try:
            clicked = await page.evaluate("""
                async () => {
                    const sleep = (ms) => new Promise(r => setTimeout(r, ms));
                    const all = document.querySelectorAll('button, input[type="submit"], a');
                    for (const el of all) {
                        if (el.offsetParent === null) continue;
                        if (el.disabled) continue;
                        const rawText = (el.innerText || el.value || '').trim();
                        if (rawText.length > 100) continue;
                        const bg = window.getComputedStyle(el).backgroundColor;
                        if (bg === 'rgb(26, 115, 232)' || bg === 'rgb(66, 133, 244)' ||
                            bg === 'rgb(23, 78, 166)' || bg === 'rgb(21, 101, 192)' ||
                            bg === 'rgb(13, 101, 45)' || bg === 'rgb(24, 90, 188)') {
                            el.scrollIntoView({block: 'center'});
                            el.focus();
                            await sleep(200);
                            el.click();
                            return { clicked: rawText.substring(0, 50), bg: bg };
                        }
                    }
                    return null;
                }
            """)
            if clicked:
                log.info(f"✅ blue button: {clicked}")
                return True
        except Exception:
            pass

        # ✅ 4. آخر زر visible
        try:
            result = await page.evaluate("""
                () => {
                    const all = document.querySelectorAll('button, input[type="submit"]');
                    const visible = Array.from(all).filter(b => 
                        b.offsetParent !== null && !b.disabled
                    );
                    for (let i = visible.length - 1; i >= 0; i--) {
                        const el = visible[i];
                        const text = (el.innerText || el.value || '').trim();
                        if (text.length < 100) {
                            el.click();
                            return { clicked: text.substring(0, 80) };
                        }
                    }
                    return null;
                }
            """)
            if result:
                log.info(f"✅ last button: {result}")
                return True
        except Exception:
            pass

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
                'button:has-text("Accept")',
                'button:has-text("I agree")',
                'button:has-text("Agree")',
                'button:has-text("I understand")',
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

    # ==================== CAPTCHA Fill ====================

    async def _fill_captcha(self, page, solution: str):
        for sel in [
            'input[name="ca"]',
            'input[id="ca"]',
            'input[name="captcha"]',
            'input[type="text"][aria-label*="Type the text" i]',
            'input[type="text"][aria-label*="characters" i]',
        ]:
            try:
                inp = page.locator(sel).first
                if await inp.count() == 0 or not await inp.is_visible():
                    continue
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
                                await human_delay(5, 8)
                                return True
                        except Exception:
                            continue
                    return True
            except Exception as e:
                log.warning(f"فشل {sel}: {e}")
                continue
        return False

    # ==================== Sign In ====================

    async def _do_signin(self, page, username: str, password: str):
        await take_screenshot(page, "cc_before_signin")

        # ✅ EMAIL
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
                await human_delay(1, 2)
                await el.fill("")
                await human_delay(0.5, 1.0)
                await el.fill(username)
                log.info("⏳ نستنى 3s بعد كتابة email...")
                await human_delay(3, 5)

                val = await el.input_value()
                if val.strip():
                    email_filled = True
                    break

                await el.click()
                await page.keyboard.type(username, delay=80)
                await human_delay(3, 5)
                val = await el.input_value()
                if val.strip():
                    email_filled = True
                    break
            except Exception as e:
                log.warning(f"فشل {sel}: {e}")
                continue

        if not email_filled:
            raise RuntimeError("❌ فشل email")

        # ✅ Next email
        log.info("🖱️ نضغط Next (email)")
        await self._click_next(page, "email")
        log.info("⏳ نستنى 8s بعد Next...")
        await human_delay(8, 12)
        await take_screenshot(page, "cc_after_email_next")

        # ✅ CAPTCHA (إذا كانت)
        try:
            from automation.captcha_solver import detect_and_solve_captcha
            solution = await detect_and_solve_captcha(
                page,
                user_id=self.user_id,
                sender=self.sender,
                context=None,
            )
            if solution:
                log.info(f"✅ CAPTCHA solved (after email)")
                await self._fill_captcha(page, solution)
                log.info("⏳ نستنى 8s بعد CAPTCHA...")
                await human_delay(8, 12)
                await take_screenshot(page, "cc_after_captcha")
        except Exception as e:
            log.warning(f"CAPTCHA: {e}")

        # ✅ PASSWORD
        log.info("⏳ نستنى 5s قبل password...")
        await human_delay(5, 8)
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
                await human_delay(1, 2)
                await el.fill("")
                await human_delay(0.5, 1.0)
                await el.fill(password)
                log.info("⏳ نستنى 3s بعد كتابة password...")
                await human_delay(3, 5)
                val = await el.input_value()
                if val.strip():
                    password_filled = True
                    break

                await el.click()
                await page.keyboard.type(password, delay=80)
                await human_delay(3, 5)
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

        # ✅ Next password
        log.info("🖱️ نضغط Next (password)")
        await self._click_next(page, "password")
        log.info("⏳ نستنى 12s بعد Next password...")
        await human_delay(12, 18)
        await take_screenshot(page, "cc_after_pwd_next")
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
        await human_delay(5, 8)
        await take_screenshot(page, "cc_console_ready")
