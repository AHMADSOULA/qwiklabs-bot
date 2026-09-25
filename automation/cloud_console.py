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

    async def login(self, username: str, password: str,
                    user_id: int = None, sender=None, context=None):
        self.username = username
        self.password = password
        self.user_id = user_id
        self.sender = sender

        page = await self.context.new_page()
        log.info("تسجيل الدخول...")

        await page.goto("https://console.cloud.google.com", wait_until="domcontentloaded")
        log.info("⏳ نستنى 10s باش الصفحة تكمل...")
        await human_delay(10, 12)
        await take_screenshot(page, "cc_01_loaded")
        log.info(f"URL: {page.url}")

        try:
            for attempt in range(8):
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
                # ✅ 2. Welcome / TOS
                # ============================================
                if await self._is_welcome_page(page):
                    log.info("📋 Welcome/TOS")
                    log.info("⏳ نستنى 10s...")
                    await human_delay(10, 12)

                    clicked = await self._handle_welcome_hard(page)
                    if clicked:
                        log.info("✅ ضغطنا — نستنى 20s")
                        await human_delay(20, 25)
                    else:
                        log.warning("⚠️ ما لقيناش Accept")
                        await human_delay(5, 8)
                    continue

                # ============================================
                # ✅ 3. CAPTCHA
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
                        await human_delay(10, 12)
                        continue
                except Exception as e:
                    log.warning(f"CAPTCHA: {e}")

                # ============================================
                # ✅ 4. Sign in?
                # ============================================
                if await self._is_signin_page(page):
                    log.info("🔑 Sign in")
                    log.info("⏳ نستنى 5s...")
                    await human_delay(5, 8)

                    try:
                        ok = await self._do_signin_with_logs(page, self.username, self.password, attempt)
                        if ok:
                            log.info("✅ sign in نجح — نستنى 12s")
                            await human_delay(12, 15)
                        else:
                            log.warning("⚠️ sign in فشل")
                            await human_delay(5, 8)
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

                log.warning(f"❓ صفحة غير معروفة: {page.url[:100]}")
                log.info("⏳ نستنى 10s...")
                await human_delay(10, 12)

            await take_screenshot(page, "cc_final_fail")
            raise RuntimeError(f"❌ فشل بعد 8 محاولات\nURL: {page.url[:200]}")

        except Exception as e:
            log.error(f"فشل: {e}")
            await take_screenshot(page, "cc_error")
            raise

    # ==================== Sign In مع Logs مفصلة ====================

    async def _do_signin_with_logs(self, page, username: str, password: str, attempt: int) -> bool:
        """
        تسجيل دخول مع Logs مفصلة فـ كل خطوة.
        """
        await take_screenshot(page, f"cc_before_signin_{attempt}")

        # ✅ نسجل الـ inputs الموجودة
        try:
            inputs = await page.evaluate("""
                () => {
                    const all = document.querySelectorAll('input');
                    return Array.from(all).map((el, i) => ({
                        idx: i,
                        type: el.type || '',
                        name: el.name || '',
                        id: el.id || '',
                        autocomplete: el.autocomplete || '',
                        visible: el.offsetParent !== null,
                        value: el.value || '',
                        ariaLabel: el.getAttribute('aria-label') || '',
                    }));
                }
            """)
            log.info(f"📋 inputs موجودة: {inputs}")
        except Exception as e:
            log.warning(f"فشل جلب inputs: {e}")

        # ✅ نسجل نص الصفحة
        try:
            body = await page.inner_text("body")
            body = body[:300].replace('\n', ' | ')
            log.info(f"📄 نص الصفحة: {body}")
        except Exception:
            pass

        # ============================================
        # ✅ EMAIL
        # ============================================
        email_filled = False
        for sel in [
            'input[type="email"]',
            'input[type="text"][name="identifier"]',
            'input[name="identifier"]',
            'input[autocomplete="username"]',
            'input[type="text"]',
        ]:
            try:
                el = page.locator(sel).first
                cnt = await el.count()
                vis = await el.is_visible() if cnt > 0 else False
                log.info(f"  🔍 {sel}: count={cnt}, visible={vis}")

                if cnt == 0 or not vis:
                    continue

                log.info(f"✅ لقيت حقل الإيميل: {sel}")

                # ✅ نستنى قبل
                await human_delay(1, 2)

                # ✅ نكليكي
                await el.click()
                await human_delay(1, 2)

                # ✅ نكتب
                await el.fill("")
                await human_delay(0.5, 1)
                await el.fill(username)
                log.info(f"  ✍️ كتبت: {username}")
                await human_delay(3, 5)

                # ✅ نتحققو
                val = await el.input_value()
                log.info(f"  📝 قيمة الحقل: '{val}'")
                if val.strip():
                    email_filled = True
                    break
            except Exception as e:
                log.warning(f"فشل {sel}: {e}")
                continue

        if not email_filled:
            log.error("❌ ما قدرتش نكتب الإيميل")
            await take_screenshot(page, f"cc_email_fail_{attempt}")
            return False

        # ✅ Next
        log.info("🖱️ نضغط Next (email)")
        next_clicked = await self._click_next_with_logs(page, "email")
        if not next_clicked:
            log.error("❌ ما لقيتش زر Next")
            return False

        log.info("⏳ نستنى 10s بعد Next (email)...")
        await human_delay(10, 15)
        await take_screenshot(page, f"cc_after_email_next_{attempt}")

        # ✅ نتحققو واش الصفحة تبدلت
        new_inputs = await page.evaluate("""
            () => {
                const all = document.querySelectorAll('input');
                return Array.from(all).map(el => ({
                    type: el.type || '',
                    name: el.name || '',
                    visible: el.offsetParent !== null,
                }));
            }
        """)
        log.info(f"📋 inputs بعد Next: {new_inputs}")

        # ============================================
        # ✅ CAPTCHA (بعد email)
        # ============================================
        try:
            from automation.captcha_solver import detect_and_solve_captcha
            solution = await detect_and_solve_captcha(
                page,
                user_id=self.user_id,
                sender=self.sender,
                context=None,
            )
            if solution:
                log.info(f"✅ CAPTCHA solved: {solution}")
                await self._fill_captcha(page, solution)
                log.info("⏳ نستنى 10s بعد CAPTCHA...")
                await human_delay(10, 15)
                await take_screenshot(page, f"cc_after_captcha_{attempt}")
        except Exception as e:
            log.warning(f"CAPTCHA: {e}")

        # ============================================
        # ✅ PASSWORD
        # ============================================
        log.info("⏳ نستنى 5s قبل password...")
        await human_delay(5, 8)
        await take_screenshot(page, f"cc_before_pwd_{attempt}")

        password_filled = False
        for sel in [
            'input[type="password"]',
            'input[name="password"]',
            'input[autocomplete="current-password"]',
        ]:
            try:
                el = page.locator(sel).first
                cnt = await el.count()
                vis = await el.is_visible() if cnt > 0 else False
                log.info(f"  🔍 {sel}: count={cnt}, visible={vis}")

                if cnt == 0 or not vis:
                    continue

                log.info(f"✅ لقيت حقل كلمة السر: {sel}")

                await human_delay(1, 2)
                await el.click()
                await human_delay(1, 2)
                await el.fill("")
                await human_delay(0.5, 1)
                await el.fill(password)
                log.info(f"  ✍️ كتبت كلمة السر")
                await human_delay(3, 5)

                val = await el.input_value()
                log.info(f"  📝 طول الحقل: {len(val)}")
                if val.strip():
                    password_filled = True
                    break
            except Exception as e:
                log.warning(f"فشل pwd {sel}: {e}")
                continue

        if not password_filled:
            log.error("❌ ما قدرتش نكتب كلمة السر")
            await take_screenshot(page, f"cc_pwd_fail_{attempt}")
            return False

        # ✅ Next password
        log.info("🖱️ نضغط Next (password)")
        next_clicked = await self._click_next_with_logs(page, "password")
        if not next_clicked:
            log.error("❌ ما لقيتش زر Next password")
            return False

        log.info("⏳ نستنى 12s بعد Next (password)...")
        await human_delay(12, 18)
        await take_screenshot(page, f"cc_after_pwd_{attempt}")

        log.info("✅ email + password done")
        return True

    async def _click_next_with_logs(self, page, step: str) -> bool:
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
                cnt = await el.count()
                vis = await el.is_visible() if cnt > 0 else False
                if cnt > 0 and vis:
                    log.info(f"  ✅ كليك على {sel} ({step})")
                    await el.click()
                    return True
            except Exception:
                continue
        return False

    # ==================== Welcome Hard Click ====================

    async def _handle_welcome_hard(self, page) -> bool:
        await human_delay(3, 5)

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

        # ✅ JS 5-event
        try:
            clicked = await page.evaluate("""
                async () => {
                    const sleep = (ms) => new Promise(r => setTimeout(r, ms));
                    function findBtn() {
                        const all = document.querySelectorAll('button, a, [role="button"]');
                        for (const el of all) {
                            if (el.offsetParent === null) continue;
                            if (el.disabled) continue;
                            const t = (el.innerText || el.value || '').trim().toLowerCase();
                            if (t === 'accept' || t === 'i understand' || t === 'i agree' ||
                                t === 'agree' || t === 'continue') return el;
                        }
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

        # ✅ Playwright
        for sel in [
            'button:has-text("Accept")',
            'button:has-text("I understand")',
            'button:has-text("I agree")',
            'button:has-text("Agree")',
            'button:has-text("Continue")',
            'button[type="submit"]',
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

    async def _do_signin(self, page, username: str, password: str):
        # Wrapper
        return await self._do_signin_with_logs(page, username, password, 0)

    async def _click_next(self, page, step: str):
        return await self._click_next_with_logs(page, step)

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
