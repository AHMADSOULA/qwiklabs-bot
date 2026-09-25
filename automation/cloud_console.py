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
        self.captcha_count = 0
        self.speedbump_attempts = 0

    async def login(self, username: str, password: str, user_id: int = None, sender=None):
        self.username = username
        self.password = password
        self.user_id = user_id
        self.sender = sender

        page = await self.context.new_page()
        log.info("تسجيل الدخول...")
        await page.goto("https://console.cloud.google.com", wait_until="domcontentloaded")
        await human_delay(3, 5)
        await take_screenshot(page, "cc_loaded")

        for attempt in range(8):
            log.info(f"=== محاولة {attempt + 1} ===")
            await human_delay(2, 3)
            await take_screenshot(page, f"cc_attempt_{attempt}")
            log.info(f"URL: {page.url[:120]}")

            # ✅ 1. Console ready?
            if await self._is_console_ready(page):
                log.info("✅ Console ready!")
                await human_delay(3, 5)
                return page

            # ✅ 2. Speedbump / TOS / Welcome
            if await self._is_speedbump_or_tos(page):
                log.info("📋 Speedbump/TOS — نعالجو")
                handled = await self._handle_speedbump(page)
                if handled:
                    self.speedbump_attempts += 1
                    log.info(f"✅ TOS {self.speedbump_attempts}")
                    await human_delay(10, 15)  # ✅ انتظار طويل بعد
                    continue
                else:
                    log.warning("⚠️ ما قدرناش نعالجو TOS")
                    await human_delay(5, 8)
                    continue

            # ✅ 3. CAPTCHA
            try:
                from automation.captcha_solver import has_captcha, detect_and_solve_captcha
                if await has_captcha(page) and self.captcha_count < 5:
                    log.info("🚨 CAPTCHA")
                    solution = await detect_and_solve_captcha(
                        page, user_id=self.user_id, sender=self.sender
                    )
                    if solution:
                        self.captcha_count += 1
                        await human_delay(5, 8)
                        continue
            except Exception as e:
                log.warning(f"CAPTCHA: {e}")

            # ✅ 4. Sign in?
            if await self._is_signin(page):
                log.info("🔑 Sign in")
                try:
                    await self._do_signin(page)
                    await human_delay(6, 10)
                except Exception as e:
                    log.warning(f"signin: {e}")
                continue

            # ✅ 5. Verify?
            if await self._has_verify(page):
                await take_screenshot(page, "cc_verify")
                raise RuntimeError("❌ Google كتطلب verify")

            log.warning(f"❓ صفحة: {page.url[:100]}")
            await human_delay(4, 6)

        await take_screenshot(page, "cc_final")
        raise RuntimeError(f"❌ فشل بعد 8 محاولات\nURL: {page.url[:200]}")

    # ==================== Speedbump / TOS ====================

    async def _is_speedbump_or_tos(self, page) -> bool:
        """يتحقق واش صفحة Speedbump/TOS"""
        url = page.url.lower()
        if "speedbump" in url or "workspacetermsofservice" in url:
            return True

        # من نص الصفحة
        try:
            text = (await page.inner_text("body")).lower()
            if "welcome to your new account" in text:
                return True
            if "terms of service" in text and ("i agree" in text or "i understand" in text):
                return True
            if "google cloud platform terms" in text:
                return True
        except Exception:
            pass

        # من checkbox
        try:
            cb_count = await page.locator('input[type="checkbox"]').count()
            if cb_count > 0:
                return True
        except Exception:
            pass

        return False

    async def _handle_speedbump(self, page) -> bool:
        """يتعامل مع صفحة Speedbump/TOS"""
        log.info("🔍 نحلل صفحة Speedbump...")

        # ✅ 1. نسجل كل العناصر
        try:
            info = await page.evaluate("""
                () => {
                    const r = {
                        url: window.location.href,
                        checkboxes: [],
                        buttons: [],
                        selects: [],
                        text_snippet: (document.body.innerText || '').substring(0, 300),
                    };
                    for (const cb of document.querySelectorAll('input[type="checkbox"]')) {
                        if (cb.offsetParent === null) continue;
                        r.checkboxes.push({
                            name: cb.name || '',
                            id: cb.id || '',
                            checked: cb.checked,
                        });
                    }
                    for (const b of document.querySelectorAll('button, a[role="button"], input[type="submit"]')) {
                        if (b.offsetParent === null) continue;
                        const t = (b.innerText || b.value || '').trim();
                        if (t && t.length < 100) {
                            r.buttons.push({
                                tag: b.tagName,
                                text: t.substring(0, 60),
                                disabled: b.disabled || false,
                            });
                        }
                    }
                    for (const s of document.querySelectorAll('select')) {
                        if (s.offsetParent === null) continue;
                        r.selects.push({
                            name: s.name || '',
                            id: s.id || '',
                            value: s.value,
                        });
                    }
                    return r;
                }
            """)
            log.info(f"📋 Checkboxes: {info.get('checkboxes')}")
            log.info(f"📋 Buttons: {info.get('buttons')}")
            log.info(f"📋 Selects: {info.get('selects')}")
        except Exception as e:
            log.warning(f"فشل تحليل: {e}")

        # ✅ 2. نختار Country (إذا كان)
        try:
            selects = page.locator('select')
            cnt = await selects.count()
            if cnt > 0:
                sel = selects.first
                current = await sel.input_value()
                log.info(f"🌍 Country الحالي: {current}")
                # ✅ نختار United States إذا ما كانش
                if not current or current == "":
                    try:
                        await sel.select_option(label="United States")
                        log.info("✅ اخترنا United States")
                    except Exception:
                        try:
                            await sel.select_option(value="US")
                        except Exception:
                            pass
                    await human_delay(1, 2)
        except Exception as e:
            log.warning(f"select: {e}")

        # ✅ 3. نضغط على checkbox
        try:
            clicked = await page.evaluate("""
                () => {
                    for (const cb of document.querySelectorAll('input[type="checkbox"]')) {
                        if (cb.offsetParent === null) continue;
                        if (cb.checked) return { already: true };
                        
                        // ✅ scroll + focus
                        cb.scrollIntoView({block: 'center'});
                        cb.focus();
                        
                        // ✅ label click
                        const label = cb.closest('label');
                        if (label) {
                            label.click();
                        } else {
                            cb.click();
                        }
                        
                        // ✅ events
                        cb.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                        cb.dispatchEvent(new Event('change', { bubbles: true }));
                        
                        return { checked: cb.checked };
                    }
                    return null;
                }
            """)
            if clicked:
                log.info(f"✅ Checkbox: {clicked}")
                await human_delay(2, 3)
        except Exception as e:
            log.warning(f"checkbox: {e}")

        # ✅ 4. نضغط على Continue
        await human_delay(2, 3)

        try:
            clicked = await page.evaluate("""
                async () => {
                    const sleep = (ms) => new Promise(r => setTimeout(r, ms));
                    const keywords = ['continue', 'agree', 'accept', 'submit', 'ok', 'yes', 'i agree'];
                    
                    for (const el of document.querySelectorAll('button, a, [role="button"], input[type="submit"]')) {
                        if (el.offsetParent === null) continue;
                        if (el.disabled) continue;
                        const t = (el.innerText || el.value || '').trim().toLowerCase();
                        if (!t || t.length > 100) continue;
                        
                        for (const kw of keywords) {
                            if (t === kw || t.includes(kw)) {
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
                                
                                return { clicked: t.substring(0, 50), tag: el.tagName };
                            }
                        }
                    }
                    return null;
                }
            """)
            if clicked:
                log.info(f"✅ Continue: {clicked}")
                await human_delay(5, 8)
                return True
        except Exception as e:
            log.warning(f"continue: {e}")

        # ✅ 5. Playwright fallback
        for sel in [
            'button:has-text("Continue")',
            'button:has-text("Agree")',
            'button:has-text("Accept")',
            'button:has-text("I agree")',
            '[role="button"]:has-text("Continue")',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible() and not await el.is_disabled():
                    log.info(f"✅ Playwright: {sel}")
                    try:
                        await el.click(timeout=3000)
                    except Exception:
                        await el.click(force=True, timeout=3000)
                    await human_delay(5, 8)
                    return True
            except Exception:
                continue

        return False

    # ==================== Sign In ====================

    async def _is_signin(self, page) -> bool:
        url = page.url.lower()
        if "accounts.google.com" in url and "workspaceterms" not in url and "speedbump" not in url:
            return True
        for sel in ['input[type="email"]', 'input[name="identifier"]', 'input[type="password"]']:
            try:
                if await page.locator(sel).count() > 0:
                    return True
            except Exception:
                pass
        return False

    async def _do_signin(self, page):
        await take_screenshot(page, "cc_before_signin")

        # EMAIL
        email_filled = False
        for sel in ['input[type="email"]', 'input[name="identifier"]', 'input[type="text"]']:
            try:
                el = page.locator(sel).first
                if await el.count() == 0 or not await el.is_visible():
                    continue
                log.info(f"✅ email: {sel}")
                await el.click()
                await human_delay(0.5, 1)
                await el.fill("")
                await human_delay(0.3, 0.5)
                await el.fill(self.username)
                await human_delay(1, 2)
                if (await el.input_value()).strip():
                    email_filled = True
                    break
                await el.click()
                await page.keyboard.type(self.username, delay=60)
                await human_delay(1, 2)
                if (await el.input_value()).strip():
                    email_filled = True
                    break
            except Exception:
                continue

        if not email_filled:
            raise RuntimeError("فشل email")

        await self._click_next(page, "email")
        await human_delay(5, 8)
        await take_screenshot(page, "cc_after_email")

        # CAPTCHA
        try:
            from automation.captcha_solver import has_captcha, detect_and_solve_captcha
            if await has_captcha(page) and self.captcha_count < 5:
                solution = await detect_and_solve_captcha(page, user_id=self.user_id, sender=self.sender)
                if solution:
                    self.captcha_count += 1
                    await human_delay(5, 8)
        except Exception:
            pass

        # PASSWORD
        await human_delay(3, 5)
        await take_screenshot(page, "cc_before_pwd")

        pwd_filled = False
        for sel in ['input[type="password"]', 'input[name="password"]']:
            try:
                el = page.locator(sel).first
                if await el.count() == 0 or not await el.is_visible():
                    continue
                log.info(f"✅ pwd: {sel}")
                await el.click()
                await human_delay(0.5, 1)
                await el.fill("")
                await human_delay(0.3, 0.5)
                await el.fill(self.password)
                await human_delay(1, 2)
                if (await el.input_value()).strip():
                    pwd_filled = True
                    break
                await el.click()
                await page.keyboard.type(self.password, delay=60)
                await human_delay(1, 2)
                if (await el.input_value()).strip():
                    pwd_filled = True
                    break
            except Exception:
                continue

        if not pwd_filled:
            raise RuntimeError("فشل pwd")

        await self._click_next(page, "password")
        await human_delay(8, 12)
        await take_screenshot(page, "cc_after_pwd")

    async def _click_next(self, page, step: str):
        for sel in ['#identifierNext', '#passwordNext', '#captchaNext',
                    'button:has-text("Next")', 'button[type="submit"]']:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.click()
                    return
            except Exception:
                continue

    async def _is_console_ready(self, page) -> bool:
        url = page.url
        if "console.cloud.google.com" not in url:
            return False
        if "signin" in url.lower() or "accounts.google.com" in url:
            return False
        return True

    async def _has_verify(self, page) -> bool:
        try:
            c = (await page.content()).lower()
            for txt in ['verify it', 'verify your', 'enter the code', '2-step']:
                if txt in c:
                    return True
        except Exception:
            pass
        return False
