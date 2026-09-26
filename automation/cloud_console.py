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

        for step in range(15):
            log.info(f"═══ خطوة {step + 1}/15 ═══")
            await human_delay(2, 3)
            await take_screenshot(page, f"cc_step_{step}")
            log.info(f"URL: {page.url[:120]}")

            # ✅ 1. Console ready?
            if await self._is_console_ready(page):
                log.info("✅ Console ready!")
                await self._send_shot(page, "✅ Console ready")
                await human_delay(3, 5)
                return page

            # ✅ 2. TOS / Welcome
            if await self._is_tos(page):
                log.info("📋 صفحة TOS")
                await self._send_shot(page, "📋 TOS")

                url_before = page.url

                clicked = await self._click_i_understand(page)
                if clicked:
                    log.info(f"✅ ضغطنا: '{clicked}'")
                    await self._send_shot(page, f"✅ ضغطنا I understand")

                    log.info("⏳ ننتظر 15s باش Google تسجل...")
                    await human_delay(15, 20)

                    changed = await self._wait_for_url_change(page, url_before, timeout=15)
                    if changed:
                        log.info("🎉 الصفحة تبدلت!")
                        await self._send_shot(page, "🎉 بعد TOS")
                        await human_delay(5, 8)
                        continue
                    else:
                        log.warning("⚠️ الصفحة ما تبدلتش — نعاود")
                        await human_delay(5, 8)
                        continue
                else:
                    log.warning("⚠️ ما لقيناش I understand")
                    await human_delay(5, 8)
                    continue

            # ✅ 3. CAPTCHA
            try:
                from automation.captcha_solver import has_captcha, detect_and_solve_captcha
                if await has_captcha(page):
                    log.info("🚨 CAPTCHA")
                    await self._send_shot(page, "🚨 CAPTCHA")
                    if self.captcha_count >= 5:
                        raise RuntimeError("CAPTCHA متكررة (5 مرات)")
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
                await self._send_shot(page, "🔑 Sign in")
                try:
                    result = await self._do_signin(page)
                    if result == "ok":
                        await self._send_shot(page, "✅ بعد sign in")
                        await human_delay(8, 12)
                        continue
                    else:
                        log.warning(f"⚠️ sign in: {result}")
                        await human_delay(5, 8)
                        continue
                except Exception as e:
                    log.warning(f"signin: {e}")
                continue

            # ✅ 5. Verify
            if await self._has_verify(page):
                raise RuntimeError("🔴 Google كتطلب verify (2FA)")

            log.warning(f"❓ صفحة: {page.url[:100]}")
            await human_delay(5, 8)

        raise RuntimeError(f"❌ فشل بعد 15 خطوة\nURL: {page.url[:200]}")

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
        """
        يضغط على I understand بـ 5 طرق.
        """
        log.info("🔍 نبحث عن I understand...")

        # ✅ نسجل الأزرار
        button_info = None
        try:
            buttons = await page.evaluate("""
                () => {
                    const r = [];
                    for (const el of document.querySelectorAll('button, a, [role="button"], input[type="submit"]')) {
                        if (el.offsetParent === null) continue;
                        const rect = el.getBoundingClientRect();
                        const bg = window.getComputedStyle(el).backgroundColor;
                        const t = (el.innerText || el.value || '').trim();
                        if (t && t.length < 100) {
                            r.push({
                                text: t.substring(0, 80),
                                bg: bg,
                                x: rect.x + rect.width / 2,
                                y: rect.y + rect.height / 2,
                                w: rect.width,
                                h: rect.height,
                            });
                        }
                    }
                    return r;
                }
            """)
            log.info(f"📋 الأزرار: {buttons}")

            keywords = ['i understand', 'understand', 'accept', 'i agree', 'agree', 'continue']
            for b in buttons:
                txt = (b.get("text") or "").lower()
                for kw in keywords:
                    if kw in txt:
                        button_info = b
                        break
                if button_info:
                    break

            if not button_info:
                for b in buttons:
                    bg = b.get("bg", "")
                    if "11, 87" in bg or "26, 115" in bg or "66, 133" in bg:
                        button_info = b
                        break
        except Exception as e:
            log.warning(f"فشل جلب الأزرار: {e}")

        if not button_info:
            log.warning("⚠️ ما لقيناش الزر")
            return None

        target_text = button_info.get("text", "")
        target_x = button_info.get("x", 0)
        target_y = button_info.get("y", 0)
        log.info(f"🎯 الزر: '{target_text}' فـ ({target_x}, {target_y})")

        # ============================================
        # ✅ الطريقة 1: Playwright locator
        # ============================================
        log.info("🖱️ الطريقة 1: Playwright locator")
        try:
            sel = f'button:has-text("{target_text}")'
            el = page.locator(sel).first
            if await el.count() > 0 and await el.is_visible():
                await el.scroll_into_view_if_needed()
                await human_delay(0.3, 0.5)
                await el.click(timeout=5000)
                log.info("✅ طريقة 1 نجحت")
                await human_delay(2, 3)
                return target_text
        except Exception as e:
            log.warning(f"طريقة 1 فشلت: {e}")

        # ============================================
        # ✅ الطريقة 2: mouse.click بالإحداثيات
        # ============================================
        log.info(f"🖱️ الطريقة 2: mouse.click على ({target_x}, {target_y})")
        try:
            if target_x > 0 and target_y > 0:
                await page.mouse.move(target_x, target_y, steps=15)
                await human_delay(0.5, 0.8)
                await page.mouse.down()
                await human_delay(0.1, 0.2)
                await page.mouse.up()
                log.info("✅ طريقة 2 نجحت")
                await human_delay(2, 3)
                return target_text
        except Exception as e:
            log.warning(f"طريقة 2 فشلت: {e}")

        # ============================================
        # ✅ الطريقة 3: dispatchEvent 5 أحداث
        # ============================================
        log.info("🖱️ الطريقة 3: dispatchEvent 5 أحداث")
        try:
            dispatched = await page.evaluate("""
                () => {
                    const keywords = ['i understand', 'understand', 'accept', 'i agree', 'agree', 'continue'];
                    const all = document.querySelectorAll('button, a, [role="button"], input[type="submit"]');
                    for (const el of all) {
                        if (el.offsetParent === null || el.disabled) continue;
                        const text = (el.innerText || el.value || '').trim().toLowerCase();
                        if (!text || text.length > 100) continue;
                        for (const kw of keywords) {
                            if (text.includes(kw)) {
                                const rect = el.getBoundingClientRect();
                                const cx = rect.x + rect.width / 2;
                                const cy = rect.y + rect.height / 2;
                                const opts = {bubbles: true, cancelable: true, view: window, clientX: cx, clientY: cy, button: 0};
                                el.dispatchEvent(new PointerEvent('pointerdown', opts));
                                el.dispatchEvent(new MouseEvent('mousedown', opts));
                                el.dispatchEvent(new PointerEvent('pointerup', opts));
                                el.dispatchEvent(new MouseEvent('mouseup', opts));
                                el.dispatchEvent(new MouseEvent('click', opts));
                                return text;
                            }
                        }
                    }
                    return null;
                }
            """)
            if dispatched:
                log.info(f"✅ طريقة 3 نجحت: {dispatched}")
                await human_delay(2, 3)
                return dispatched
        except Exception as e:
            log.warning(f"طريقة 3 فشلت: {e}")

        # ============================================
        # ✅ الطريقة 4: JS click
        # ============================================
        log.info("🖱️ الطريقة 4: JS click")
        try:
            clicked = await page.evaluate("""
                () => {
                    const keywords = ['i understand', 'understand', 'accept', 'i agree', 'agree', 'continue'];
                    const all = document.querySelectorAll('button, a, [role="button"], input[type="submit"], input[type="button"]');
                    for (const el of all) {
                        if (el.offsetParent === null || el.disabled) continue;
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
                log.info(f"✅ طريقة 4 نجحت: {clicked}")
                await human_delay(2, 3)
                return clicked
        except Exception as e:
            log.warning(f"طريقة 4 فشلت: {e}")

        # ============================================
        # ✅ الطريقة 5: آخر زر أزرق
        # ============================================
        log.info("🖱️ الطريقة 5: آخر زر أزرق")
        try:
            clicked = await page.evaluate("""
                () => {
                    const all = document.querySelectorAll('button, input[type="submit"], a[role="button"]');
                    for (const el of all) {
                        if (el.offsetParent === null || el.disabled) continue;
                        const bg = window.getComputedStyle(el).backgroundColor;
                        if (bg.includes('11, 87') || bg.includes('26, 115') || bg.includes('66, 133')) {
                            el.click();
                            return (el.innerText || '').substring(0, 80) || 'blue-button';
                        }
                    }
                    return null;
                }
            """)
            if clicked:
                log.info(f"✅ طريقة 5 نجحت: {clicked}")
                await human_delay(2, 3)
                return clicked
        except Exception as e:
            log.warning(f"طريقة 5 فشلت: {e}")

        return None

    async def _wait_for_url_change(self, page, url_before: str, timeout: int = 15) -> bool:
        log.info(f"⏳ ننتظر URL يتغير...")
        for i in range(timeout):
            await asyncio.sleep(1)
            if page.url != url_before:
                log.info(f"✅ URL تبدل")
                return True
            try:
                has_i_understand = await page.evaluate("""
                    () => {
                        for (const el of document.querySelectorAll('button, [role="button"]')) {
                            if (el.offsetParent === null) continue;
                            const t = (el.innerText || '').trim().toLowerCase();
                            if (t.includes('understand') || t === 'accept') return true;
                        }
                        return false;
                    }
                """)
                if not has_i_understand:
                    log.info("✅ الزر اختفى — الصفحة تبدلت")
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

    # ==================== Sign In ====================

    async def _do_signin(self, page) -> str:
        await self._send_shot(page, "📸 قبل sign in")

        # EMAIL — keyboard.type
        email_ok = False
        for sel in ['input[type="email"]', 'input[name="identifier"]', 'input[type="text"]']:
            try:
                el = page.locator(sel).first
                if await el.count() == 0 or not await el.is_visible():
                    continue
                log.info(f"✅ email: {sel}")

                await el.scroll_into_view_if_needed()
                await el.click()
                await human_delay(0.5, 1)
                await page.keyboard.press("Control+a")
                await human_delay(0.2, 0.4)
                await page.keyboard.press("Delete")
                await human_delay(0.3, 0.5)
                await page.keyboard.type(self.username, delay=80)
                await human_delay(1, 2)

                val = await el.input_value()
                if val.strip() and "@" in val:
                    email_ok = True
                    await self._send_shot(page, f"✅ email")
                    break

                await el.evaluate("""(el, val) => {
                    el.focus();
                    el.value = '';
                    for (const ch of val) {
                        el.value += ch;
                        el.dispatchEvent(new KeyboardEvent('keydown', {key: ch, bubbles: true}));
                        el.dispatchEvent(new Event('input', {bubbles: true}));
                        el.dispatchEvent(new KeyboardEvent('keyup', {key: ch, bubbles: true}));
                    }
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                }""", self.username)
                await human_delay(1, 2)
                val = await el.input_value()
                if val.strip() and "@" in val:
                    email_ok = True
                    break
            except Exception:
                continue

        if not email_ok:
            return "فشل email"

        await self._click_next(page, "email")
        await human_delay(6, 10)
        await self._send_shot(page, "📸 بعد email Next")

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

        await human_delay(5, 8)
        await self._send_shot(page, "📸 قبل password")

        # PASSWORD
        pwd_ok = False
        for sel in ['input[type="password"]', 'input[name="password"]']:
            try:
                el = page.locator(sel).first
                if await el.count() == 0 or not await el.is_visible():
                    continue
                log.info(f"✅ pwd: {sel}")

                await el.scroll_into_view_if_needed()
                await el.click()
                await human_delay(0.5, 1)
                await page.keyboard.press("Control+a")
                await human_delay(0.2, 0.4)
                await page.keyboard.press("Delete")
                await human_delay(0.3, 0.5)
                await page.keyboard.type(self.password, delay=80)
                await human_delay(1, 2)

                val = await el.input_value()
                if val.strip():
                    pwd_ok = True
                    await self._send_shot(page, f"✅ password")
                    break

                await el.evaluate("""(el, val) => {
                    el.focus();
                    el.value = '';
                    for (const ch of val) {
                        el.value += ch;
                        el.dispatchEvent(new KeyboardEvent('keydown', {key: ch, bubbles: true}));
                        el.dispatchEvent(new Event('input', {bubbles: true}));
                        el.dispatchEvent(new KeyboardEvent('keyup', {key: ch, bubbles: true}));
                    }
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                }""", self.password)
                await human_delay(1, 2)
                val = await el.input_value()
                if val.strip():
                    pwd_ok = True
                    break
            except Exception:
                continue

        if not pwd_ok:
            return "فشل password"

        await self._click_next(page, "password")
        await human_delay(10, 15)
        await self._send_shot(page, "📸 بعد password Next")
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
