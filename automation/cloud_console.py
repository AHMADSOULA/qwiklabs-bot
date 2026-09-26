import asyncio
from utils.logger import get_logger
from utils.helpers import human_delay, human_move
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
        log.info("تسجيل الدخول إلى Cloud Console...")
        await page.goto("https://console.cloud.google.com", wait_until="domcontentloaded")
        await human_delay(3, 5)

        # ✅ Screenshot: عند دخول SSO/Console
        await self._send_shot(page, "1️⃣ دخول SSO")

        try:
            for attempt in range(6):
                log.info(f"--- محاولة {attempt + 1} ---")
                await human_delay(2, 3)
                log.info(f"URL: {page.url[:120]}")

                # 🔍 كلمة سر غلط؟
                if await self._has_wrong_password_error(page):
                    await self._send_shot(page, "❌ كلمة سر غلط")
                    await self._send_report(page, "❌ كلمة السر غير صحيحة")
                    raise RuntimeError("❌ كلمة السر غير صحيحة.")

                # 🔍 verify؟
                if await self._has_verify_required(page):
                    await self._send_shot(page, "⚠️ Verify مطلوب")
                    await self._send_report(page, "⚠️ Google كتطلب verify")
                    raise RuntimeError("⚠️ Google كتطلب verify")

                # ✅ Welcome / TOS؟
                if await self._is_welcome_page(page):
                    log.info("📋 صفحة Welcome")
                    # ✅ Screenshot: عند Welcome
                    await self._send_shot(page, "2️⃣ صفحة Welcome")

                    clicked = await self._click_blue_button(page)
                    if not clicked:
                        await self._send_report(page, "❌ ما قدرناش نضغط الزر الأزرق")
                        raise RuntimeError("❌ ما قدرناش نضغط Accept")

                    log.info("✅ ضغطنا Accept — نستنى Google")
                    await human_delay(10, 15)
                    continue

                # ✅ Console ready؟
                if await self._is_console_ready(page):
                    log.info("✅ وصلنا للـ Console!")
                    # ✅ Screenshot: عند دخول Google Cloud
                    await self._send_shot(page, "3️⃣ دخل Google Cloud")
                    break

                # ✅ Sign in؟
                if await self._is_signin_page(page):
                    log.info("🔑 Sign in")
                    try:
                        await self._do_signin(page, self.username, self.password)
                        await human_delay(5, 8)
                    except Exception as e:
                        log.warning(f"⚠️ sign in: {e}")
                    continue

                await human_delay(3, 5)

            await self._wait_for_console(page, timeout=30000)
            log.info(f"✅ URL النهائي: {page.url}")
            return page

        except Exception as e:
            log.error(f"فشل تسجيل الدخول: {e}")
            await self._send_shot(page, "❌ فشل")
            raise

    # ==================== Screenshot + Report ====================

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
                        await self.sender.reply_photo(
                            photo=InputFile(f),
                            caption=caption[:1000]
                        )
                except Exception as e:
                    log.warning(f"فشل إرسال الصورة: {e}")
        except Exception as e:
            log.warning(f"_send_shot: {e}")

    async def _send_report(self, page, reason: str):
        """يرسل تقرير عند المشكل"""
        try:
            if not self.sender:
                return

            info = await page.evaluate("""
                () => {
                    const text = (document.body.innerText || '').substring(0, 400).replace(/\\n+/g, ' | ');
                    const buttons = [];
                    for (const b of document.querySelectorAll('button, [role="button"], a[role="button"]')) {
                        if (b.offsetParent === null) continue;
                        const t = (b.innerText || '').trim();
                        const bg = window.getComputedStyle(b).backgroundColor;
                        if (t && t.length < 60) buttons.push(t + ' [' + bg + ']');
                    }
                    return {
                        url: window.location.href.substring(0, 200),
                        text: text,
                        buttons: buttons.slice(0, 10),
                    };
                }
            """)

            msg = f"""🔴 *تقرير المشكل*

📋 *السبب:* {reason}

🔗 *URL:*
`{info.get('url', '')[:180]}`

📄 *النص:*
```{info.get('text', '')[:250]}```

🔘 *الأزرار:*
"""
            for b in info.get("buttons", []):
                msg += f"\n  • `{b}`"

            try:
                await self.sender.reply_text(msg[:4000], parse_mode="Markdown")
            except Exception:
                await self.sender.reply_text(msg[:4000])

        except Exception as e:
            log.warning(f"_send_report: {e}")

    # ==================== Click Blue Button ====================

    async def _click_blue_button(self, page) -> bool:
        """
        يضغط على الزر الأزرق (I understand / Agree and continue)
        باستعمال mouse.click بالإحداثيات.
        """
        log.info("🔍 نبحث عن الزر الأزرق...")

        # ✅ 1. نسجل الأزرار مع إحداثياتها
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
        except Exception as e:
            log.warning(f"فشل جلب الأزرار: {e}")
            buttons = []

        # ✅ 2. نلقاو الزر الأزرق
        target = None
        for b in buttons:
            bg = b.get("bg", "")
            txt = (b.get("text") or "").lower()
            # ✅ أزرار Google الزرقاء
            if "11, 87" in bg or "26, 115" in bg or "66, 133" in bg or \
               "under" in txt or "agree" in txt or "accept" in txt or "continue" in txt:
                target = b
                break

        if not target:
            # ✅ نلقاو آخر زر أزرق
            for b in buttons:
                bg = b.get("bg", "")
                if "11, 87" in bg or "26, 115" in bg or "66, 133" in bg:
                    target = b
                    break

        if not target:
            log.warning("⚠️ ما لقيناش زر أزرق")
            return False

        x = target.get("x", 0)
        y = target.get("y", 0)
        text = target.get("text", "")
        log.info(f"🎯 الزر الأزرق: '{text}' فـ ({x}, {y})")

        # ✅ 3. نضغطو بـ mouse.click
        try:
            await page.mouse.move(x, y, steps=15)
            await human_delay(0.5, 1)
            await page.mouse.down()
            await human_delay(0.1, 0.2)
            await page.mouse.up()
            log.info("✅ ضغطنا بـ mouse.click")
            return True
        except Exception as e:
            log.warning(f"mouse.click فشل: {e}")

        # ✅ 4. Playwright
        for sel in [
            'button:has-text("I understand")',
            'button:has-text("Agree and continue")',
            'button:has-text("I agree")',
            'button:has-text("Accept")',
            'button:has-text("Continue")',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.click(force=True, timeout=5000)
                    log.info(f"✅ Playwright: {sel}")
                    return True
            except Exception:
                continue

        # ✅ 5. JS click (fallback)
        try:
            clicked = await page.evaluate("""
                () => {
                    const kws = ['i understand', 'agree and continue', 'i agree', 'accept', 'continue', 'agree'];
                    for (const el of document.querySelectorAll('button, a, [role="button"]')) {
                        if (el.offsetParent === null || el.disabled) continue;
                        const t = (el.innerText || el.value || '').trim().toLowerCase();
                        if (!t || t.length > 100) continue;
                        for (const kw of kws) {
                            if (t.includes(kw)) {
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
                log.info(f"✅ JS: {clicked}")
                return True
        except Exception:
            pass

        # ✅ 6. آخر زر أزرق (fallback)
        try:
            clicked = await page.evaluate("""
                () => {
                    for (const el of document.querySelectorAll('button, input[type="submit"]')) {
                        if (el.offsetParent === null || el.disabled) continue;
                        const bg = window.getComputedStyle(el).backgroundColor;
                        if (bg.includes('11, 87') || bg.includes('26, 115') || bg.includes('66, 133')) {
                            el.click();
                            return (el.innerText || '').substring(0, 80);
                        }
                    }
                    return null;
                }
            """)
            if clicked:
                log.info(f"✅ آخر زر أزرق: {clicked}")
                return True
        except Exception:
            pass

        return False

    # ==================== دوال الفحص ====================

    async def _is_welcome_page(self, page) -> bool:
        try:
            url = page.url.lower()
            if "welcome" in url or "/new" in url:
                return True
            info = await page.evaluate("""
                () => {
                    const text = (document.body.innerText || '').toLowerCase();
                    const has_welcome = text.includes('welcome to your new account') ||
                                        (text.includes('terms of service') && text.includes('i understand'));
                    let has_blue = false;
                    for (const el of document.querySelectorAll('button, [role="button"]')) {
                        if (el.offsetParent === null) continue;
                        const bg = window.getComputedStyle(el).backgroundColor;
                        if (bg.includes('11, 87') || bg.includes('26, 115') || bg.includes('66, 133')) {
                            has_blue = true;
                            break;
                        }
                    }
                    return { has_welcome, has_blue };
                }
            """)
            if info.get("has_welcome") or info.get("has_blue"):
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
        if "/welcome" in url.lower() or "/new" in url.lower():
            return False
        try:
            text = (await page.inner_text("body")).lower()
            if "welcome to your new account" in text:
                return False
        except Exception:
            pass
        return "project=" in url or "/home/" in url

    async def _is_signin_page(self, page) -> bool:
        url = page.url
        if "accounts.google.com" in url:
            return True
        if "signin" in url.lower():
            return True
        for sel in ['input[type="email"]', 'input[name="identifier"]', 'input[type="password"]']:
            try:
                if await page.locator(sel).count() > 0:
                    return True
            except Exception:
                pass
        return False

    # ==================== Sign In ====================

    async def _do_signin(self, page, username: str, password: str):
        # Email
        email_filled = False
        for sel in [
            'input[type="email"]',
            'input[type="text"][name="identifier"]',
            'input[name="identifier"]',
            'input[type="text"]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() == 0 or not await el.is_visible():
                    continue
                log.info(f"✅ حقل الإيميل: {sel}")
                await el.click()
                await human_delay(0.5, 1.0)
                await el.fill("")
                await human_delay(0.2, 0.5)
                await el.fill(username)
                await human_delay(0.5, 1.0)
                if (await el.input_value()).strip():
                    email_filled = True
                    break
                # type fallback
                await el.click()
                await page.keyboard.type(username, delay=60)
                await human_delay(0.5, 1.0)
                if (await el.input_value()).strip():
                    email_filled = True
                    break
            except Exception:
                continue

        if not email_filled:
            raise RuntimeError("ما قدرتش نكتب الإيميل")

        await self._click_next(page, "email")
        await human_delay(4, 6)

        # CAPTCHA
        try:
            from automation.captcha_solver import has_captcha, detect_and_solve_captcha
            for _ in range(5):
                await human_delay(3, 5)
                if await has_captcha(page):
                    log.info("🚨 CAPTCHA")
                    await self._send_shot(page, "🚨 CAPTCHA")
                    solved = await detect_and_solve_captcha(page)
                    if solved:
                        log.info(f"✅ CAPTCHA: {solved}")
                        await human_delay(4, 6)
                        break
                else:
                    break
        except Exception as e:
            log.warning(f"CAPTCHA: {e}")

        # Password
        await human_delay(3, 5)
        password_filled = False
        for sel in ['input[type="password"]', 'input[name="password"]']:
            try:
                el = page.locator(sel).first
                if await el.count() == 0 or not await el.is_visible():
                    continue
                log.info(f"✅ حقل كلمة السر: {sel}")
                await el.click()
                await human_delay(0.5, 1.0)
                await el.fill("")
                await human_delay(0.2, 0.5)
                await el.fill(password)
                await human_delay(0.5, 1.0)
                if (await el.input_value()).strip():
                    password_filled = True
                    break
                await el.click()
                await page.keyboard.type(password, delay=60)
                await human_delay(0.5, 1.0)
                if (await el.input_value()).strip():
                    password_filled = True
                    break
            except Exception:
                continue

        if not password_filled:
            raise RuntimeError("ما قدرتش نكتب كلمة السر")

        await self._click_next(page, "password")
        await human_delay(8, 12)
        log.info("✅ email + password done")

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

    async def _wait_for_console(self, page, timeout: int = 30000):
        log.info("انتظار Console...")
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
