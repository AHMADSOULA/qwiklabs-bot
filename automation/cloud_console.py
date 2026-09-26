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

    async def login(self, username: str, password: str, user_id: int = None, sender=None):
        self.username = username
        self.password = password
        self.user_id = user_id
        self.sender = sender

        page = await self.context.new_page()
        log.info("تسجيل الدخول إلى Cloud Console...")
        await page.goto("https://console.cloud.google.com", wait_until="domcontentloaded")
        await human_delay(3, 5)
        await self._send_shot(page, "📸 فتح Cloud Console")
        log.info(f"URL بعد الفتح: {page.url}")

        try:
            for attempt in range(3):
                log.info(f"--- محاولة {attempt + 1} ---")
                await self._wait_for_login_or_console(page)

                if await self._has_wrong_password_error(page):
                    log.warning("⚠️ كلمة السر غلط!")
                    await self._send_shot(page, "❌ كلمة سر غلط")
                    raise RuntimeError("❌ كلمة السر غير صحيحة.\nجدد الرابط من Skills.")

                if await self._has_verify_required(page):
                    log.warning("⚠️ Google كتطلب verify phone/email")
                    await self._send_shot(page, "⚠️ Verify مطلوب")
                    raise RuntimeError("❌ Google كتطلب التحقق من الهاتف.")

                if await self._is_signin_page(page):
                    log.info(f"🔑 صفحة Sign in (محاولة {attempt + 1})")
                    await self._send_shot(page, "📸 صفحة Sign in")
                    await self._do_signin(page, self.username, self.password)
                    await human_delay(5, 7)

                # Welcome / TOS
                await self._handle_welcome_page(page)
                await human_delay(4, 6)

                if await self._is_console_ready(page):
                    log.info(f"✅ وصلنا للـ Console")
                    await self._send_shot(page, "✅ دخل Google Cloud")
                    break

                await human_delay(3, 5)

            await self._wait_for_console(page, timeout=30000)
            log.info(f"✅ URL النهائي: {page.url}")
            return page

        except Exception as e:
            log.error(f"فشل تسجيل الدخول: {e}")
            await self._send_shot(page, "❌ فشل")
            raise

    # ==================== Screenshot Helper ====================

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

    # ==========================================
    # 🔍 دوال الفحص
    # ==========================================

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
        if "project=" in url:
            return True
        if "/home/" in url:
            return True
        return False

    async def _wait_for_login_or_console(self, page, timeout: int = 25000):
        try:
            await page.wait_for_function(
                """() => {
                    return document.querySelector('input[type="email"]') ||
                           document.querySelector('input[type="text"]') ||
                           document.querySelector('input[type="password"]') ||
                           window.location.href.includes('console.cloud.google.com');
                }""",
                timeout=timeout,
            )
        except Exception:
            log.warning("Timeout فـ انتظار الصفحة")
        await human_delay(2, 3)

    async def _is_signin_page(self, page) -> bool:
        url = page.url
        if "accounts.google.com" in url:
            return True
        if "signin" in url.lower():
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

    # ==========================================
    # 🔐 تسجيل الدخول
    # ==========================================

    async def _do_signin(self, page, username: str, password: str):
        # ========== Email ==========
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
                if await el.count() == 0 or not await el.is_visible():
                    continue
                log.info(f"✅ حقل الإيميل: {sel}")
                await el.click()
                await human_delay(0.5, 1.0)
                await el.fill("")
                await human_delay(0.2, 0.5)
                await el.fill(username)
                await human_delay(0.3, 0.8)

                val = await el.input_value()
                if val.strip():
                    log.info(f"✅ طريقة 1 نجحت")
                    email_filled = True
                    break

                log.warning("fill ما خدمش — نجرب type")
                await el.click()
                await human_delay(0.3, 0.5)
                await page.keyboard.type(username, delay=50)
                await human_delay(0.3, 0.8)

                val = await el.input_value()
                if val.strip():
                    log.info(f"✅ طريقة 2 نجحت")
                    email_filled = True
                    break
            except Exception as e:
                log.warning(f"فشل مع {sel}: {e}")
                continue

        if not email_filled:
            await self._send_shot(page, "❌ فشل email")
            raise RuntimeError("ما قدرتش نكتب الإيميل")

        await self._click_next(page, "email")
        await human_delay(3, 5)

        # ============================================
        # 🔍 CAPTCHA — فحص متعدد (5 محاولات)
        # ============================================
        for captcha_attempt in range(5):
            log.info(f"🔍 فحص CAPTCHA ({captcha_attempt + 1}/5)...")
            await human_delay(3, 5)

            try:
                from automation.captcha_solver import has_captcha, detect_and_solve_captcha
                from config import config

                if await has_captcha(page):
                    log.info("🚨 CAPTCHA مطلوبة!")
                    await self._send_shot(page, "🚨 CAPTCHA")

                    solved = await detect_and_solve_captcha(
                        page,
                        config.CAPTCHA_USERID,
                        config.CAPTCHA_APIKEY,
                    )
                    if solved:
                        log.info(f"✅ تم حل CAPTCHA: {solved}")
                        await human_delay(4, 6)
                        break
                    else:
                        log.warning("⚠️ CAPTCHA ما تحلّتش")
                        await human_delay(3, 5)
                else:
                    log.info("✅ ما كاينش CAPTCHA")
                    break

            except Exception as e:
                log.warning(f"فشل فحص CAPTCHA: {e}")
                await human_delay(2, 3)

        # ============================================
        # ⏳ ننتظر حقل password (بلا page.evaluate)
        # ============================================
        log.info("⏳ ننتظر حقل password...")
        for wait_attempt in range(10):
            try:
                pwd = page.locator('input[type="password"]').first
                if await pwd.count() > 0:
                    log.info("✅ حقل password ظهر")
                    break
            except Exception:
                pass
            await human_delay(2, 3)

        # ========== Password ==========
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
                log.info(f"✅ حقل كلمة السر: {sel}")
                await el.click()
                await human_delay(0.5, 1.0)
                await el.fill("")
                await human_delay(0.2, 0.5)
                await el.fill(password)
                await human_delay(0.3, 0.8)

                val = await el.input_value()
                if val.strip():
                    log.info(f"✅ كلمة السر (طريقة 1)")
                    password_filled = True
                    break

                log.warning("fill ما خدمش — type")
                await el.click()
                await human_delay(0.3, 0.5)
                await page.keyboard.type(password, delay=50)
                await human_delay(0.3, 0.8)

                val = await el.input_value()
                if val.strip():
                    log.info(f"✅ كلمة السر (طريقة 2)")
                    password_filled = True
                    break
            except Exception as e:
                log.warning(f"فشل كلمة السر مع {sel}: {e}")
                continue

        if not password_filled:
            await self._send_shot(page, "❌ فشل password")
            raise RuntimeError("ما قدرتش نكتب كلمة السر")

        await self._click_next(page, "password")
        await human_delay(4, 7)

        log.info("✅ تم إدخال email + password")

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

    # ==========================================
    # ✅ Welcome / TOS — Playwright مباشرة
    # ==========================================

    async def _handle_welcome_page(self, page, max_attempts: int = 3) -> bool:
        for attempt in range(max_attempts):
            log.info(f"🔍 Welcome/TOS محاولة {attempt + 1}")
            await human_delay(3, 5)

            # ✅ 1. Checkbox
            try:
                cb = page.locator('input[type="checkbox"]').first
                if await cb.count() > 0:
                    try:
                        is_checked = await cb.is_checked()
                    except Exception:
                        is_checked = False

                    if not is_checked:
                        log.info("📋 نضغط على checkbox...")
                        try:
                            await cb.check(timeout=5000)
                            log.info("✅ Checkbox checked")
                        except Exception:
                            try:
                                await cb.click(force=True)
                                log.info("✅ Checkbox clicked")
                            except Exception as e:
                                log.warning(f"checkbox: {e}")
                        await human_delay(1, 2)
                    else:
                        log.info("✅ Checkbox already checked")
            except Exception as e:
                log.warning(f"checkbox: {e}")

            # ✅ 2. زر Agree
            for sel in [
                'button:has-text("Agree and continue")',
                'button:has-text("I understand")',
                'button:has-text("I agree")',
                'button:has-text("Accept")',
                'button:has-text("Agree")',
                'button:has-text("Continue")',
                'button:has-text("Got it")',
            ]:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0 and await el.is_visible():
                        log.info(f"✅ لقيت: {sel}")
                        try:
                            await el.click(timeout=5000)
                        except Exception:
                            await el.click(force=True)
                        log.info(f"✅ ضغطنا: {sel}")
                        await human_delay(5, 8)
                        return True
                except Exception:
                    continue

            # ✅ 3. الزر الأزرق
            try:
                for blue_sel in [
                    'button[style*="rgb(26, 115"]',
                    'button[style*="rgb(11, 87"]',
                    'button[style*="rgb(66, 133"]',
                ]:
                    blue = page.locator(blue_sel).first
                    if await blue.count() > 0 and await blue.is_visible():
                        log.info(f"✅ Blue button: {blue_sel}")
                        await blue.click()
                        await human_delay(5, 8)
                        return True
            except Exception:
                pass

            await human_delay(3, 5)

        return False

    # ==========================================
    # ✅ انتظار Console
    # ==========================================

    async def _wait_for_console(self, page, timeout: int = 30000):
        log.info("انتظار تحميل Cloud Console...")
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
            log.warning("Timeout فـ انتظار Console")

        await human_delay(5, 8)

        try:
            import time
            path = f"/app/data/screenshots/{int(time.time())}_cc_ready.png"
            await page.screenshot(path=path, full_page=False, timeout=10000)
            log.info(f"📸 {path}")
        except Exception as e:
            log.warning(f"فشل screenshot: {e}")
