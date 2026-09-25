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
        self.tos_clicked = False

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

        for attempt in range(6):
            log.info(f"=== محاولة {attempt + 1} ===")
            await human_delay(2, 3)
            await take_screenshot(page, f"cc_attempt_{attempt}")

            # ✅ 1. Console ready?
            if await self._is_console_ready(page):
                log.info("✅ Console ready!")
                await human_delay(3, 5)
                return page

            # ✅ 2. Dialog / TOS
            if await self._handle_dialog(page):
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
        raise RuntimeError(f"❌ فشل بعد 6 محاولات\nURL: {page.url[:200]}")

    # ============ Dialog ============

    async def _handle_dialog(self, page) -> bool:
        """يتعامل مع Dialog (TOS / Welcome)"""
        try:
            has = await page.evaluate("""
                () => {
                    for (const d of document.querySelectorAll('[role="dialog"], mat-dialog-container, .modal')) {
                        if (d.offsetParent === null) continue;
                        const t = (d.innerText || '').toLowerCase();
                        if (t.includes('terms of service') || t.includes('i agree') || t.includes('welcome student')) return true;
                    }
                    for (const cb of document.querySelectorAll('input[type="checkbox"]')) {
                        if (cb.offsetParent !== null) return true;
                    }
                    return false;
                }
            """)
            if not has:
                return False

            log.info("📋 Dialog — نضغط checkbox + Continue")

            # checkbox
            try:
                await page.evaluate("""
                    () => {
                        for (const cb of document.querySelectorAll('input[type="checkbox"]')) {
                            if (cb.offsetParent === null || cb.checked) continue;
                            cb.scrollIntoView({block: 'center'});
                            const lb = cb.closest('label');
                            if (lb) lb.click(); else cb.click();
                            cb.dispatchEvent(new Event('change', { bubbles: true }));
                            return true;
                        }
                        return false;
                    }
                """)
                await human_delay(1, 2)
            except Exception:
                pass

            # Continue
            try:
                clicked = await page.evaluate("""
                    () => {
                        const kws = ['continue', 'agree', 'accept', 'i agree', 'ok', 'yes'];
                        for (const el of document.querySelectorAll('button, a, [role="button"], input[type="submit"]')) {
                            if (el.offsetParent === null || el.disabled) continue;
                            const t = (el.innerText || el.value || '').trim().toLowerCase();
                            if (!t || t.length > 100) continue;
                            for (const kw of kws) {
                                if (t === kw || t.includes(kw)) {
                                    el.scrollIntoView({block: 'center'});
                                    el.click();
                                    return t;
                                }
                            }
                        }
                        return null;
                    }
                """)
                if clicked:
                    log.info(f"✅ ضغطنا: {clicked}")
                    await human_delay(5, 8)
                    return True
            except Exception:
                pass

            # Playwright fallback
            for sel in ['button:has-text("Continue")', 'button:has-text("Accept")', 'button:has-text("I agree")']:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0 and await el.is_visible():
                        await el.click(timeout=3000)
                        return True
                except Exception:
                    continue
            return False
        except Exception as e:
            log.warning(f"Dialog: {e}")
            return False

    # ============ Sign In ============

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
                log.info(f"✅ email field: {sel}")
                await el.click()
                await human_delay(0.5, 1)
                await el.fill("")
                await human_delay(0.3, 0.5)
                await el.fill(self.username)
                await human_delay(1, 2)
                if (await el.input_value()).strip():
                    email_filled = True
                    break
                # type fallback
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

        # CAPTCHA بعد email
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
                log.info(f"✅ pwd field: {sel}")
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
