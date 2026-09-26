import asyncio
import json
import time
import os
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

        # ✅ Screenshot 1: فتح Console
        await self._shot(page, "1️⃣ فتح Cloud Console")

        try:
            for attempt in range(5):
                log.info(f"--- محاولة {attempt + 1} ---")
                await human_delay(2, 3)
                log.info(f"URL: {page.url[:120]}")

                # 🔍 كلمة سر غلط؟
                if await self._has_wrong_password_error(page):
                    await self._shot(page, "❌ كلمة سر غلط")
                    raise RuntimeError("❌ كلمة السر غير صحيحة.")

                # 🔍 verify؟
                if await self._has_verify_required(page):
                    await self._shot(page, "⚠️ Verify مطلوب")
                    raise RuntimeError("⚠️ Google كتطلب verify")

                # ✅ 1. Sign in؟ (نفحصو أولاً — فيه input)
                if await self._is_signin_page(page):
                    log.info("🔑 Sign in")
                    await self._shot(page, "2️⃣ صفحة Sign in")

                    try:
                        await self._do_signin(page, self.username, self.password)
                        await human_delay(5, 8)
                    except Exception as e:
                        log.warning(f"⚠️ sign in: {e}")
                        await self._shot(page, "❌ فشل Sign in")
                        # ✅ نرسل التقرير
                        await self._send_report(page, f"فشل Sign in: {str(e)[:200]}")
                        raise
                    continue

                # ✅ 2. Welcome / TOS؟
                if await self._is_welcome_page(page):
                    log.info("📋 Welcome/TOS")
                    await self._shot(page, "3️⃣ صفحة Welcome")

                    clicked = await self._click_blue_button(page)
                    if clicked:
                        log.info(f"✅ ضغطنا: {clicked}")
                        await self._shot(page, "✅ ضغطنا Accept")
                        await human_delay(10, 15)
                    else:
                        # ❌ ما لقيناش زر
                        await self._shot(page, "❌ ما لقيناش زر")
                        await self._send_report(page, "❌ ما لقيناش زر Accept فـ Welcome")
                        await human_delay(5, 8)
                    continue

                # ✅ 3. Console ready؟
                if await self._is_console_ready(page):
                    log.info("✅ وصلنا للـ Console!")
                    await self._shot(page, "4️⃣ دخل Google Cloud")
                    break

                log.warning(f"❓ صفحة غير معروفة")
                await human_delay(3, 5)

            await self._wait_for_console(page, timeout=30000)
            log.info(f"✅ URL النهائي: {page.url}")
            return page

        except Exception as e:
            log.error(f"فشل تسجيل الدخول: {e}")
            await self._shot(page, "❌ فشل")
            raise

    # ==================== Shot + Report ====================

    async def _shot(self, page, caption: str = ""):
        """Screenshot + إرسال فـ Telegram"""
        try:
            from telegram import InputFile
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
            log.warning(f"_shot: {e}")

    async def _send_report(self, page, reason: str):
        """يرسل تقرير مفصّل عن المشكل"""
        try:
            # ✅ نجمع كل المعلومات
            info = await page.evaluate("""
                () => {
                    const url = window.location.href.substring(0, 300);
                    const title = document.title || '';
                    const text = (document.body.innerText || '').substring(0, 1000).replace(/\\n+/g, ' | ');

                    const buttons = [];
                    for (const el of document.querySelectorAll('button, a, [role="button"], input[type="submit"]')) {
                        if (el.offsetParent === null) continue;
                        const rect = el.getBoundingClientRect();
                        const bg = window.getComputedStyle(el).backgroundColor;
                        const t = (el.innerText || el.value || '').trim();
                        if (t && t.length < 80) {
                            buttons.push({
                                text: t.substring(0, 80),
                                tag: el.tagName,
                                id: el.id || '',
                                cls: (el.className || '').toString().substring(0, 60),
                                bg: bg,
                                x: Math.round(rect.x + rect.width / 2),
                                y: Math.round(rect.y + rect.height / 2),
                                w: Math.round(rect.width),
                                h: Math.round(rect.height),
                                disabled: el.disabled || false,
                            });
                        }
                    }

                    const inputs = [];
                    for (const el of document.querySelectorAll('input, textarea, select')) {
                        if (el.offsetParent === null) continue;
                        const rect = el.getBoundingClientRect();
                        inputs.push({
                            tag: el.tagName,
                            type: el.type || '',
                            name: el.name || '',
                            id: el.id || '',
                            aria: el.getAttribute('aria-label') || '',
                            placeholder: el.placeholder || '',
                            value: (el.value || '').substring(0, 30),
                            formcontrolname: el.getAttribute('formcontrolname') || '',
                            x: Math.round(rect.x + rect.width / 2),
                            y: Math.round(rect.y + rect.height / 2),
                        });
                    }

                    const iframes = document.querySelectorAll('iframe').length;

                    return { url, title, text, buttons, inputs, iframes };
                }
            """)

            # ✅ نحفظ JSON
            try:
                os.makedirs("/app/data/records", exist_ok=True)
                path = f"/app/data/records/error_{int(time.time())}.json"
                with open(path, "w", encoding="utf-8") as f:
                    json.dump({"reason": reason, **info}, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

            # ✅ نبني الرسالة
            msg = f"🔴 *تقرير المشكل*\n\n"
            msg += f"📋 *السبب:* {reason}\n\n"
            msg += f"🔗 *URL:*\n`{info.get('url', '')[:200]}`\n\n"
            msg += f"📄 *العنوان:* `{info.get('title', '')[:80]}`\n\n"
            msg += f"📝 *النص:*\n```{info.get('text', '')[:300]}```\n\n"
            msg += f"🔘 *الأزرار ({len(info.get('buttons', []))}):*\n"
            for b in info.get("buttons", [])[:15]:
                msg += f"  • `{b['text']}` — bg:`{b['bg']}` @({b['x']},{b['y']})\n"

            msg += f"\n📝 *الحقول ({len(info.get('inputs', []))}):*\n"
            for i in info.get("inputs", [])[:15]:
                msg += f"  • type=`{i['type']}` name=`{i['name']}` aria=`{i['aria'][:30]}`\n"

            msg += f"\n🖼️ *iframes:* {info.get('iframes', 0)}"

            # ✅ نرسل (مقسّم)
            if self.sender:
                try:
                    for i in range(0, len(msg), 3500):
                        try:
                            await self.sender.reply_text(msg[i:i+3500], parse_mode="Markdown")
                        except Exception:
                            await self.sender.reply_text(msg[i:i+3500])
                except Exception:
                    pass

        except Exception as e:
            log.warning(f"_send_report: {e}")

    # ==================== دوال الفحص ====================

    async def _is_signin_page(self, page) -> bool:
        """✅ فحص قوي — نفحصو قبل Welcome"""
        try:
            url = page.url.lower()
            if "accounts.google.com" in url:
                return True
            if "signin" in url and "workspaceterms" not in url:
                return True
            # ✅ إذا كاين input[email] → Sign in
            has_input = await page.evaluate("""
                () => {
                    for (const inp of document.querySelectorAll('input')) {
                        if (inp.offsetParent === null) continue;
                        if (inp.type === 'email' || inp.name === 'identifier' || inp.type === 'password') {
                            return true;
                        }
                    }
                    return false;
                }
            """)
            return bool(has_input)
        except Exception:
            return False

    async def _is_welcome_page(self, page) -> bool:
        """✅ نفحصو Welcome — ماشي Sign in"""
        try:
            url = page.url.lower()
            if "accounts.google.com" in url:
                return False

            # ✅ إذا كاين input[email] → Sign in ماشي Welcome
            has_email = await page.evaluate("""
                () => {
                    for (const inp of document.querySelectorAll('input')) {
                        if (inp.offsetParent === null) continue;
                        if (inp.type === 'email' || inp.name === 'identifier') return true;
                    }
                    return false;
                }
            """)
            if has_email:
                return False

            # ✅ من URL
            if "workspacetermsofservice" in url or "speedbump" in url:
                return True

            # ✅ من النص + زر
            info = await page.evaluate("""
                () => {
                    const text = (document.body.innerText || '').toLowerCase();
                    const has_welcome = text.includes('welcome to your new account') ||
                                        (text.includes('terms of service') && text.includes('i understand'));
                    let has_understand = false;
                    for (const el of document.querySelectorAll('button, [role="button"]')) {
                        if (el.offsetParent === null) continue;
                        const t = (el.innerText || '').trim().toLowerCase();
                        if (t.includes('i understand') || t.includes('agree and continue')) {
                            has_understand = true;
                            break;
                        }
                    }
                    return { has_welcome, has_understand };
                }
            """)
            return bool(info.get("has_welcome") or info.get("has_understand"))
        except Exception:
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

    # ==================== Click Blue Button ====================

    async def _click_blue_button(self, page) -> str:
        """يضغط على الزر الأزرق"""
        log.info("🔍 نبحث عن الزر الأزرق...")

        # ✅ نسجل الأزرار
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
                                x: Math.round(rect.x + rect.width / 2),
                                y: Math.round(rect.y + rect.height / 2),
                                disabled: el.disabled || false,
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

        # ✅ نلقاو الزر
        target = None
        for b in buttons:
            txt = (b.get("text") or "").lower()
            if "i understand" in txt or "agree and continue" in txt or "accept" in txt or "continue" in txt:
                target = b
                break

        # ✅ أو زر أزرق
        if not target:
            for b in buttons:
                bg = b.get("bg", "")
                if "11, 87" in bg or "26, 115" in bg or "66, 133" in bg:
                    target = b
                    break

        if not target:
            log.warning("⚠️ ما لقيناش زر")
            return None

        x = target.get("x", 0)
        y = target.get("y", 0)
        text = target.get("text", "")
        log.info(f"🎯 الزر: '{text}' فـ ({x}, {y})")

        # ✅ نضغطو
        try:
            if x > 0 and y > 0:
                await page.mouse.move(x, y, steps=15)
                await human_delay(0.5, 1)
                await page.mouse.down()
                await human_delay(0.1, 0.2)
                await page.mouse.up()
                log.info("✅ mouse.click")
                return text
        except Exception as e:
            log.warning(f"mouse: {e}")

        # ✅ Playwright
        for sel in [
            'button:has-text("I understand")',
            'button:has-text("Agree and continue")',
            'button:has-text("Accept")',
            'button:has-text("Continue")',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.click(force=True, timeout=5000)
                    log.info(f"✅ {sel}")
                    return sel
            except Exception:
                continue

        # ✅ JS
        try:
            clicked = await page.evaluate("""
                () => {
                    const kws = ['i understand', 'agree and continue', 'accept', 'continue', 'agree'];
                    for (const el of document.querySelectorAll('button, a, [role="button"]')) {
                        if (el.offsetParent === null || el.disabled) continue;
                        const t = (el.innerText || '').trim().toLowerCase();
                        for (const kw of kws) {
                            if (t.includes(kw)) {
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
                return clicked
        except Exception:
            pass

        return None

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
                log.info(f"✅ email: {sel}")
                await el.click()
                await human_delay(0.5, 1.0)
                await el.fill("")
                await human_delay(0.2, 0.5)
                await el.fill(username)
                await human_delay(0.5, 1.0)
                if (await el.input_value()).strip():
                    email_filled = True
                    break
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
                    await self._shot(page, "🚨 CAPTCHA")
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
        pwd_filled = False
        for sel in ['input[type="password"]', 'input[name="password"]']:
            try:
                el = page.locator(sel).first
                if await el.count() == 0 or not await el.is_visible():
                    continue
                log.info(f"✅ pwd: {sel}")
                await el.click()
                await human_delay(0.5, 1.0)
                await el.fill("")
                await human_delay(0.2, 0.5)
                await el.fill(password)
                await human_delay(0.5, 1.0)
                if (await el.input_value()).strip():
                    pwd_filled = True
                    break
                await el.click()
                await page.keyboard.type(password, delay=60)
                await human_delay(0.5, 1.0)
                if (await el.input_value()).strip():
                    pwd_filled = True
                    break
            except Exception:
                continue

        if not pwd_filled:
            raise RuntimeError("ما قدرتش نكتب password")

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
