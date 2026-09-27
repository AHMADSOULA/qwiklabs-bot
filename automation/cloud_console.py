import asyncio
import json
import time
import os
from utils.logger import get_logger
from utils.helpers import human_delay, human_move
from utils.screenshot import take_screenshot

log = get_logger("CloudConsole")


class CloudConsole:
    """كلاس مسؤول عن تسجيل الدخول إلى Google Cloud Console."""

    def __init__(self, context):
        self.context = context
        self.username = None
        self.password = None
        self.user_id = None
        self.sender = None

    # ==================== تسجيل الدخول ====================

    async def login(self, username: str, password: str, user_id: int = None, sender=None):
        self.username = username
        self.password = password
        self.user_id = user_id
        self.sender = sender

        page = await self.context.new_page()
        log.info("🔐 بدء تسجيل الدخول إلى Cloud Console...")
        await page.goto("https://console.cloud.google.com", wait_until="domcontentloaded")
        await human_delay(3, 5)
        await self._shot(page, "1️⃣ فتح Cloud Console")

        try:
            for attempt in range(5):
                log.info(f"--- المحاولة {attempt + 1} ---")
                await human_delay(2, 3)
                log.info(f"URL الحالي: {page.url[:120]}")

                # ❌ كلمة سر خاطئة؟
                if await self._has_wrong_password_error(page):
                    await self._shot(page, "❌ كلمة سر غلط")
                    raise RuntimeError("❌ كلمة السر غير صحيحة.")

                # ⚠️ مطلوب التحقق؟
                if await self._has_verify_required(page):
                    await self._shot(page, "⚠️ Verify مطلوب")
                    raise RuntimeError("⚠️ Google تطلب التحقق (verify)")

                # ✅ 1. صفحة تسجيل الدخول
                if await self._is_signin_page(page):
                    log.info("🔑 صفحة Sign in")
                    await self._shot(page, "2️⃣ صفحة Sign in")
                    try:
                        await self._do_signin(page, self.username, self.password)
                        await human_delay(5, 8)
                    except Exception as e:
                        log.warning(f"⚠️ فشل تسجيل الدخول: {e}")
                        await self._shot(page, "❌ فشل Sign in")
                        await self._send_report(page, f"فشل Sign in: {str(e)[:200]}")
                        raise
                    continue

                # ✅ 2. صفحة الترحيب / شروط الخدمة
                if await self._is_welcome_page(page):
                    log.info("📋 صفحة Welcome / TOS")
                    await self._shot(page, "3️⃣ صفحة Welcome")

                    clicked = await self._click_blue_button(page)
                    if clicked:
                        log.info(f"✅ تم الضغط على: {clicked}")
                        await self._shot(page, "✅ تم قبول الشروط")
                        await human_delay(10, 15)
                    else:
                        await self._shot(page, "❌ لم نجد الزر")
                        await self._send_report(page, "❌ لم نجد زر Accept في صفحة Welcome")
                        await human_delay(5, 8)
                    continue

                # ✅ 3. الكونسول جاهز
                if await self._is_console_ready(page):
                    log.info("✅ وصلنا إلى Console!")
                    await self._shot(page, "4️⃣ تم الدخول إلى Google Cloud")
                    break

                log.warning("❓ صفحة غير معروفة")
                await human_delay(3, 5)

            await self._wait_for_console(page, timeout=30000)
            log.info(f"✅ URL النهائي: {page.url}")
            return page

        except Exception as e:
            log.error(f"فشل تسجيل الدخول: {e}")
            await self._shot(page, "❌ فشل")
            raise

    # ==================== أدوات المساعدة (صور + تقارير) ====================

    async def _shot(self, page, caption: str = ""):
        """أخذ لقطة شاشة وإرسالها عبر Telegram."""
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
                    log.warning(f"تعذّر إرسال الصورة: {e}")
        except Exception as e:
            log.warning(f"_shot: {e}")

    async def _send_report(self, page, reason: str):
        """إرسال تقرير مفصّل عند حدوث مشكل."""
        try:
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

            # حفظ التقرير محليًا
            try:
                os.makedirs("/app/data/records", exist_ok=True)
                path = f"/app/data/records/error_{int(time.time())}.json"
                with open(path, "w", encoding="utf-8") as f:
                    json.dump({"reason": reason, **info}, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

            # بناء الرسالة
            msg = "🔴 *تقرير المشكل*\n\n"
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
        """هل نحن في صفحة تسجيل الدخول؟"""
        try:
            url = page.url.lower()
            if "accounts.google.com" in url:
                return True
            if "signin" in url and "workspaceterms" not in url:
                return True

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
        """هل نحن في صفحة الترحيب / شروط الخدمة؟"""
        try:
            url = page.url.lower()
            if "accounts.google.com" in url:
                return False

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

            if "workspacetermsofservice" in url or "speedbump" in url:
                return True

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
        """هل ظهر خطأ كلمة سر خاطئة؟"""
        try:
            content = (await page.content()).lower()
            return any(txt in content for txt in ('incorrect password', 'wrong password'))
        except Exception:
            return False

    async def _has_verify_required(self, page) -> bool:
        """هل Google تطلب تحقق؟"""
        try:
            content = (await page.content()).lower()
            return any(txt in content for txt in
                       ('verify it', 'verify your', 'enter the code', '2-step'))
        except Exception:
            return False

    async def _is_console_ready(self, page) -> bool:
        """هل وصلنا فعلاً إلى الكونسول؟"""
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

    # ==================== الضغط على الزر الأزرق (5 طرق) ====================

    async def _click_blue_button(self, page) -> str:
        """يضغط على الزر الأزرق — 5 طرق (آخرها batchexecute)"""
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
            log.warning(f"فشل: {e}")
            buttons = []

        # ✅ نلقاو الزر
        target_text = None
        for b in buttons:
            txt = (b.get("text") or "").lower()
            if "i understand" in txt or "agree and continue" in txt or "accept" in txt:
                target_text = b.get("text")
                break

        if not target_text:
            for b in buttons:
                bg = b.get("bg", "")
                if "11, 87" in bg or "26, 115" in bg or "66, 133" in bg:
                    target_text = b.get("text")
                    break

        if not target_text:
            log.warning("⚠️ ما لقيناش زر")
            return None

        log.info(f"🎯 الزر: '{target_text}'")

        # ============================================
        # ✅ الطريقة 1: Playwright locator
        # ============================================
        log.info("🖱️ الطريقة 1: Playwright")
        for sel in [
            f'button:has-text("{target_text}")',
            'button:has-text("I understand")',
            'button:has-text("Agree and continue")',
            'button:has-text("Accept")',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.scroll_into_view_if_needed()
                    await human_delay(0.3, 0.5)
                    log.info(f"✅ لقينا: {sel}")
                    await el.click(timeout=5000)
                    log.info("✅ click نجح")
                    await human_delay(2, 3)
                    if await self._is_tos_gone(page):
                        log.info("✅ TOS تبدلت!")
                        return target_text
                    log.warning("⚠️ TOS ما تبدلتش — نجربو طرق أخرى")
            except Exception as e:
                log.warning(f"فشل {sel}: {e}")
                continue

        # ============================================
        # ✅ الطريقة 2: force click
        # ============================================
        log.info("🖱️ الطريقة 2: force")
        try:
            for sel in ['button:has-text("I understand")', 'button:has-text("Agree and continue")']:
                el = page.locator(sel).first
                if await el.count() > 0:
                    await el.click(force=True, timeout=5000)
                    log.info(f"✅ force: {sel}")
                    await human_delay(2, 3)
                    if await self._is_tos_gone(page):
                        log.info("✅ TOS تبدلت!")
                        return target_text
        except Exception as e:
            log.warning(f"force: {e}")

        # ============================================
        # ✅ الطريقة 3: JS click + dispatch events
        # ============================================
        log.info("🖱️ الطريقة 3: JS + events")
        try:
            clicked = await page.evaluate("""
                () => {
                    const kws = ['i understand', 'agree and continue', 'accept', 'continue'];
                    for (const el of document.querySelectorAll('button, a, [role="button"]')) {
                        if (el.offsetParent === null || el.disabled) continue;
                        const t = (el.innerText || '').trim().toLowerCase();
                        if (!t || t.length > 100) continue;
                        for (const kw of kws) {
                            if (t.includes(kw)) {
                                el.scrollIntoView({block: 'center'});
                                el.focus();
                                // ✅ 5 أحداث
                                const rect = el.getBoundingClientRect();
                                const cx = rect.x + rect.width / 2;
                                const cy = rect.y + rect.height / 2;
                                const opts = {bubbles: true, cancelable: true, view: window, clientX: cx, clientY: cy, button: 0};
                                el.dispatchEvent(new PointerEvent('pointerdown', opts));
                                el.dispatchEvent(new MouseEvent('mousedown', opts));
                                el.dispatchEvent(new PointerEvent('pointerup', opts));
                                el.dispatchEvent(new MouseEvent('mouseup', opts));
                                el.dispatchEvent(new MouseEvent('click', opts));
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
                await human_delay(2, 3)
                if await self._is_tos_gone(page):
                    log.info("✅ TOS تبدلت!")
                    return target_text
        except Exception as e:
            log.warning(f"JS: {e}")

        # ============================================
        # ✅ الطريقة 4: batchexecute (Google RPC)
        # ============================================
        log.info("🖱️ الطريقة 4: batchexecute (Google RPC)")
        try:
            result = await self._call_batchexecute(page)
            if result:
                log.info(f"✅ batchexecute: {result}")
                await human_delay(3, 5)
                if await self._is_tos_gone(page):
                    log.info("✅ TOS تبدلت بـ batchexecute!")
                    return target_text
        except Exception as e:
            log.warning(f"batchexecute: {e}")

        # ============================================
        # ✅ الطريقة 5: إعادة تحميل الصفحة
        # ============================================
        log.info("🖱️ الطريقة 5: reload")
        try:
            await page.reload(wait_until="domcontentloaded")
            await human_delay(5, 8)
        except Exception:
            pass

        return target_text

    # ==================== batchexecute ====================

    async def _call_batchexecute(self, page) -> str:
        """
        يستدعي Google batchexecute API مباشرة
        (نفس الطلبات اللي JS كيرسلهم)
        """
        try:
            # ✅ نستخرجو القيم من الصفحة
            wiz_data = await page.evaluate("""
                () => {
                    const wiz = window.WIZ_global_data || {};
                    return {
                        f_sid: wiz.FdrFJe || '',
                        at: wiz.SNlM0e || '',
                        bl: wiz.cfb2h || 'boq_identityfrontendauthuiserver_20260920.02_p0',
                        dsh: wiz.Qzxixc || '',
                        hl: wiz.GWsdKe || 'ar',
                    };
                }
            """)

            log.info(f"📋 WIZ: {wiz_data}")

            if not wiz_data.get("at"):
                log.warning("⚠️ ما لقيناش SNlM0e")
                return None

            # ✅ نستدعيو batchexecute
            result = await page.evaluate("""
                async (args) => {
                    try {
                        const url = `https://accounts.google.com/v3/signin/_/WorkspaceTermsOfServiceUi/data/batchexecute?rpcids=GVthp&source-path=%2Fv3%2Fsignin%2Fspeedbump%2Fworkspacetermsofservice&f.sid=${args.f_sid}&bl=${args.bl}&hl=${args.hl}&dsh=${args.dsh}&rt=c`;

                        const body = `f.req=${encodeURIComponent(JSON.stringify([[[\"GVthp\",\"[[\\\"\\\"] ]\",null,\"generic\"]]]))}&at=${encodeURIComponent(args.at)}&`;

                        const res = await fetch(url, {
                            method: 'POST',
                            credentials: 'include',
                            headers: {
                                'content-type': 'application/x-www-form-urlencoded;charset=UTF-8',
                                'x-same-domain': '1',
                            },
                            body: body,
                        });

                        const text = await res.text();
                        return text.substring(0, 500);
                    } catch(e) {
                        return 'error: ' + e.message;
                    }
                }
            """, wiz_data)

            log.info(f"📥 batchexecute result: {result}")
            return result

        except Exception as e:
            log.warning(f"batchexecute: {e}")
            return None

    # ==================== Check TOS gone ====================

    async def _is_tos_gone(self, page) -> bool:
        """يتحقق واش خرجنا من TOS"""
        try:
            url = page.url.lower()
            if "workspacetermsofservice" in url or "speedbump" in url:
                return False
            if "welcome" in url:
                # ✅ إذا كان TOS، ما زال
                text = (await page.inner_text("body")).lower()
                if "welcome to your new account" in text:
                    return False
            return True
        except Exception:
            return False

    # ==================== خطوات تسجيل الدخول ====================

    async def _do_signin(self, page, username: str, password: str):
        """كتابة الإيميل وكلمة السر + التعامل مع CAPTCHA."""
        # ---------- الإيميل ----------
        email_filled = False
        for sel in (
            'input[type="email"]',
            'input[type="text"][name="identifier"]',
            'input[name="identifier"]',
            'input[type="text"]',
        ):
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
                await el.click()
                await page.keyboard.type(username, delay=60)
                await human_delay(0.5, 1.0)
                if (await el.input_value()).strip():
                    email_filled = True
                    break
            except Exception:
                continue

        if not email_filled:
            raise RuntimeError("تعذّر كتابة البريد الإلكتروني")

        await self._click_next(page, "email")
        await human_delay(4, 6)

        # ---------- CAPTCHA ----------
        try:
            from automation.captcha_solver import has_captcha, detect_and_solve_captcha
            for _ in range(5):
                await human_delay(3, 5)
                if await has_captcha(page):
                    log.info("🚨 CAPTCHA ظهر")
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

        # ---------- كلمة السر ----------
        await human_delay(3, 5)
        pwd_filled = False
        for sel in ('input[type="password"]', 'input[name="password"]'):
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
            raise RuntimeError("تعذّر كتابة كلمة السر")

        await self._click_next(page, "password")
        await human_delay(8, 12)
        log.info("✅ تم إدخال الإيميل وكلمة السر")

    async def _click_next(self, page, step: str):
        """الضغط على زر Next في أي خطوة."""
        for sel in (
            '#identifierNext', '#passwordNext', '#captchaNext',
            'button:has-text("Next")', 'button[type="submit"]',
        ):
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.click()
                    return
            except Exception:
                continue

    async def _wait_for_console(self, page, timeout: int = 30000):
        """انتظار تحميل الكونسول."""
        log.info("⏳ انتظار تحميل Console...")
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
            log.warning("⏱️ انتهت مدة انتظار Console")
        await human_delay(3, 5)
