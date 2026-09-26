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

    async def login(self, username: str, password: str, user_id: int = None, sender=None):
        self.username = username
        self.password = password
        self.user_id = user_id
        self.sender = sender

        page = await self.context.new_page()
        log.info("تسجيل الدخول...")
        await page.goto("https://console.cloud.google.com", wait_until="domcontentloaded")
        await human_delay(3, 5)
        await self._send_shot(page, "📸 فتح Cloud Console")

        for step in range(10):
            log.info(f"═══ خطوة {step + 1}/10 ═══")
            await human_delay(2, 3)
            await take_screenshot(page, f"cc_step_{step}")
            log.info(f"URL: {page.url[:120]}")

            # Console ready?
            if await self._is_console_ready(page):
                log.info("✅ Console ready!")
                await human_delay(3, 5)
                return page

            # TOS / Welcome
            if await self._is_tos(page):
                log.info("📋 TOS/Welcome")
                await self._send_shot(page, "📋 TOS")
                clicked = await self._click_i_understand(page)
                if clicked:
                    log.info(f"✅ ضغطنا: {clicked}")
                    await human_delay(10, 15)
                    continue
                else:
                    await human_delay(5, 8)
                    continue

            # CAPTCHA
            try:
                from automation.captcha_solver import has_captcha, detect_and_solve_captcha
                if await has_captcha(page):
                    log.info("🚨 CAPTCHA")
                    await self._send_shot(page, "🚨 CAPTCHA")
                    solution = await detect_and_solve_captcha(
                        page, user_id=self.user_id, sender=self.sender
                    )
                    if solution:
                        self.captcha_count += 1
                        await human_delay(5, 8)
                        continue
            except Exception as e:
                log.warning(f"CAPTCHA: {e}")

            # Sign in
            if await self._is_signin(page):
                log.info("🔑 Sign in")
                await self._send_shot(page, "🔑 Sign in")
                try:
                    result = await self._do_signin(page)
                    if result == "ok":
                        await human_delay(6, 10)
                        continue
                except Exception as e:
                    log.warning(f"signin: {e}")
                continue

            # Verify
            if await self._has_verify(page):
                raise RuntimeError("🔴 Google كتطلب verify (2FA)")

            log.warning(f"❓ صفحة: {page.url[:100]}")
            await human_delay(5, 8)

        raise RuntimeError(f"❌ فشل بعد 10 خطوات\nURL: {page.url[:200]}")

    # ==================== Helpers ====================

    async def _send_shot(self, page, caption: str = ""):
        try:
            from telegram import InputFile
            import os
            shot = await take_screenshot(page, caption[:30] if caption else "shot")
            if not shot or not os.path.exists(shot):
                return
            if self.sender:
                try:
                    with open(shot, "rb") as f:
                        await self.sender.reply_photo(photo=InputFile(f), caption=caption[:1000])
                except Exception:
                    pass
        except Exception:
            pass

    async def _is_tos(self, page) -> bool:
        url = page.url.lower()
        if "speedbump" in url or "workspacetermsofservice" in url:
            return True
        try:
            text = (await page.inner_text("body")).lower()
            if "welcome to your new account" in text:
                return True
            if "terms of service" in text and ("i agree" in text or "i understand" in text):
                return True
        except Exception:
            pass
        return False

    async def _click_i_understand(self, page) -> str:
        """يضغط على I understand — مرة وحدة"""
        log.info("🔍 نبحث عن I understand...")

        try:
            buttons = await page.evaluate("""
                () => {
                    const r = [];
                    for (const el of document.querySelectorAll('button, a, [role="button"], input[type="submit"]')) {
                        if (el.offsetParent === null) continue;
                        const t = (el.innerText || el.value || '').trim();
                        const bg = window.getComputedStyle(el).backgroundColor;
                        if (t && t.length < 100) {
                            r.push({text: t.substring(0, 80), bg: bg});
                        }
                    }
                    return r;
                }
            """)
            log.info(f"📋 الأزرار: {buttons}")
        except Exception:
            pass

        # ✅ JS click
        try:
            clicked = await page.evaluate("""
                () => {
                    const keywords = ['i understand', 'understand', 'accept', 'i accept',
                                      'agree', 'i agree', 'continue', 'got it'];
                    const all = document.querySelectorAll(
                        'button, a, [role="button"], input[type="submit"], input[type="button"]'
                    );
                    for (const el of all) {
                        if (el.offsetParent === null || el.disabled) continue;
                        const text = (el.innerText || el.value || el.textContent || '').trim().toLowerCase();
                        if (!text || text.length > 100) continue;
                        for (const kw of keywords) {
                            if (text.includes(kw)) {
                                el.click();
                                return text.substring(0, 80);
                            }
                        }
                    }
                    return null;
                }
            """)
            if clicked:
                return clicked
        except Exception as e:
            log.warning(f"JS: {e}")

        # ✅ Playwright
        for sel in [
            'button:has-text("I understand")',
            'button:has-text("Accept")',
            'button:has-text("Continue")',
            'button[type="submit"]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.click(timeout=5000)
                    return sel
            except Exception:
                continue

        return None

    async def _is_console_ready(self, page) -> bool:
        url = page.url
        if "console.cloud.google.com" not in url:
            return False
        if "signin" in url.lower() or "accounts.google.com" in url:
            return False
        return True

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

    async def _has_verify(self, page) -> bool:
        try:
            c = (await page.content()).lower()
            for txt in ['verify it', 'verify your', 'enter the code', '2-step']:
                if txt in c:
                    return True
        except Exception:
            pass
        return False

    async def _do_signin(self, page) -> str:
        await self._send_shot(page, "📸 قبل sign in")

        # EMAIL
        email_ok = False
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
                    email_ok = True
                    break
                await el.click()
                await page.keyboard.type(self.username, delay=60)
                await human_delay(1, 2)
                if (await el.input_value()).strip():
                    email_ok = True
                    break
            except Exception:
                continue

        if not email_ok:
            return "فشل email"

        await self._click_next(page, "email")
        await human_delay(5, 8)

        # CAPTCHA
        try:
            from automation.captcha_solver import has_captcha, detect_and_solve_captcha
            if await has_captcha(page):
                solution = await detect_and_solve_captcha(page, user_id=self.user_id, sender=self.sender)
                if solution:
                    self.captcha_count += 1
                    await human_delay(5, 8)
        except Exception:
            pass

        await human_delay(3, 5)

        # PASSWORD
        pwd_ok = False
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
                    pwd_ok = True
                    break
                await el.click()
                await page.keyboard.type(self.password, delay=60)
                await human_delay(1, 2)
                if (await el.input_value()).strip():
                    pwd_ok = True
                    break
            except Exception:
                continue

        if not pwd_ok:
            return "فشل password"

        await self._click_next(page, "password")
        await human_delay(8, 12)
        return "ok"

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
