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

        for step in range(12):
            log.info(f"═══ خطوة {step + 1}/12 ═══")
            await human_delay(2, 3)
            await take_screenshot(page, f"cc_step_{step}")
            current_url = page.url
            log.info(f"URL: {current_url[:120]}")

            # ✅ 1. Console ready?
            if await self._is_console_ready(page):
                log.info("✅ Console ready!")
                await self._send_shot(page, "✅ دخل لـ Cloud Console")
                await human_delay(3, 5)
                return page

            # ✅ 2. Speedbump / TOS / Welcome
            if await self._is_speedbump_or_tos(page):
                log.info("📋 صفحة TOS/Welcome")
                await self._send_shot(page, "📋 صفحة Terms of Service")

                log.info("🖱️ نضغط على 'I understand' مرة وحدة...")
                clicked = await self._click_i_understand_once(page)

                if not clicked:
                    await self._raise_problem(
                        page,
                        "🔴 ما لقيناش زر I understand",
                        "الصفحة فيها TOS ولكن ما لقيناش زر I understand"
                    )

                log.info(f"✅ ضغطنا على: '{clicked}' — ننتظر 15 ثانية...")
                await self._send_shot(page, f"✅ ضغطنا: {clicked}")

                await human_delay(15, 18)

                if await self._is_console_ready(page):
                    log.info("🎉 دخلنا لـ Google Cloud!")
                    await self._send_shot(page, "🎉 دخل لـ Google Cloud")
                    await human_delay(3, 5)
                    return page

                log.error("❌ ما دخلناش لـ Google Cloud")
                await self._raise_problem(
                    page,
                    "🔴 فشل بعد الضغط على I understand",
                    f"ضغطنا على '{clicked}' ولكن Google ما سجلتش. URL: {page.url[:150]}"
                )

            # ✅ 3. CAPTCHA
            try:
                from automation.captcha_solver import has_captcha, detect_and_solve_captcha
                if await has_captcha(page):
                    log.info("🚨 CAPTCHA")
                    await self._send_shot(page, "🚨 CAPTCHA")
                    if self.captcha_count >= 3:
                        await self._raise_problem(page, "🔴 CAPTCHA متكررة", "3 مرات")
                    solution = await detect_and_solve_captcha(
                        page, user_id=self.user_id, sender=self.sender
                    )
                    if solution:
                        self.captcha_count += 1
                        await self._send_shot(page, f"✅ CAPTCHA: {solution}")
                        await human_delay(5, 8)
                        continue
                    else:
                        await self._raise_problem(page, "🔴 CAPTCHA ما تحلّتش", "")
            except Exception as e:
                log.warning(f"CAPTCHA: {e}")

            # ✅ 4. Sign in?
            if await self._is_signin(page):
                log.info("🔑 Sign in")
                await self._send_shot(page, "🔑 صفحة Sign in")
                try:
                    result = await self._do_signin(page)
                    if result == "ok":
                        await self._send_shot(page, "✅ تم تسجيل الدخول")
                        await human_delay(6, 10)
                        continue
                    else:
                        await self._raise_problem(page, f"🔴 Sign in: {result}", "")
                except Exception as e:
                    await self._raise_problem(page, "🔴 Sign in exception", str(e)[:300])

            # ✅ 5. Verify?
            if await self._has_verify(page):
                await self._send_shot(page, "🔴 verify مطلوب")
                await self._raise_problem(page, "🔴 verify (2FA)", "")

            # ✅ 6. كلمة سر غلط؟
            if await self._has_wrong_password(page):
                await self._send_shot(page, "🔴 كلمة السر غلط")
                await self._raise_problem(page, "🔴 كلمة السر غلط", "")

            log.warning(f"❓ صفحة: {current_url[:100]}")
            await human_delay(5, 8)

        await self._raise_problem(page, "🔴 فشل بعد 12 خطوة", f"URL: {page.url[:200]}")

    # ==================== Click I Understand (مرة وحدة) ====================

    async def _click_i_understand_once(self, page) -> str:
        log.info("🔍 نبحث عن زر I understand...")

        try:
            buttons = await page.evaluate("""
                () => {
                    const r = [];
                    for (const el of document.querySelectorAll('button, a, [role="button"], input[type="submit"]')) {
                        if (el.offsetParent === null) continue;
                        const t = (el.innerText || el.value || '').trim();
                        if (t && t.length < 100) {
                            const bg = window.getComputedStyle(el).backgroundColor;
                            r.push({text: t.substring(0, 80), bg: bg});
                        }
                    }
                    return r;
                }
            """)
            log.info(f"📋 الأزرار: {buttons}")
        except Exception:
            pass

        try:
            clicked = await page.evaluate("""
                () => {
                    const keywords = ['i understand', 'understand', 'accept', 'i accept',
                                      'agree', 'i agree', 'confirm', 'got it', 'continue',
                                      'understood', 'قبول', 'موافق', 'أفهم'];
                    const all = document.querySelectorAll(
                        'button, a, [role="button"], input[type="submit"], input[type="button"]'
                    );
                    for (const el of all) {
                        if (el.offsetParent === null) continue;
                        if (el.disabled) continue;
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
                log.info(f"✅ ضغطنا: '{clicked}'")
                return clicked
        except Exception as e:
            log.warning(f"JS: {e}")

        try:
            clicked = await page.evaluate("""
                () => {
                    for (const el of document.querySelectorAll('button, input[type="submit"], [role="button"]')) {
                        if (el.offsetParent === null || el.disabled) continue;
                        const bg = window.getComputedStyle(el).backgroundColor;
                        if (bg.includes('11, 87') || bg.includes('26, 115') || bg.includes('66, 133')) {
                            el.click();
                            return (el.innerText || '').trim().substring(0, 80) || 'blue-button';
                        }
                    }
                    return null;
                }
            """)
            if clicked:
                log.info(f"✅ ضغطنا على الزر الأزرق: {clicked}")
                return clicked
        except Exception:
            pass

        return None

    # ==================== Helpers ====================

    async def _is_speedbump_or_tos(self, page) -> bool:
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

    async def _raise_problem(self, page, title: str, details: str):
        """
        يتوقف + يرسل Logs كاملة + Screenshot.
        """
        log.error(f"❌ {title}: {details}")
        await self._send_shot(page, f"❌ {title[:50]}")

        info = {}
        try:
            info = await page.evaluate("""
                () => {
                    const r = {
                        url: window.location.href.substring(0, 300),
                        title: document.title || '',
                        text: (document.body.innerText || '').substring(0, 800).replace(/\\n+/g, ' | '),
                        buttons: [],
                        inputs: [],
                        checkboxes: [],
                        images: [],
                        iframes: document.querySelectorAll('iframe').length,
                    };
                    for (const b of document.querySelectorAll('button, a[role="button"], input[type="submit"]')) {
                        if (b.offsetParent === null) continue;
                        const t = (b.innerText || b.value || '').trim();
                        const bg = window.getComputedStyle(b).backgroundColor;
                        if (t && t.length < 80) r.buttons.push({text: t, bg: bg});
                    }
                    for (const inp of document.querySelectorAll('input')) {
                        if (inp.offsetParent === null) continue;
                        r.inputs.push({type: inp.type, name: inp.name, id: inp.id, value: (inp.value || '').substring(0, 30)});
                    }
                    for (const cb of document.querySelectorAll('input[type="checkbox"]')) {
                        if (cb.offsetParent === null) continue;
                        r.checkboxes.push({name: cb.name, checked: cb.checked});
                    }
                    for (const img of document.querySelectorAll('img')) {
                        if (img.offsetParent === null) continue;
                        const s = (img.src || '').toLowerCase();
                        if (s.includes('captcha')) r.images.push('CAPTCHA');
                    }
                    return r;
                }
            """)
        except Exception as e:
            info = {"error": str(e)}

        # ✅ نبني الرسالة بأجزاء (بلا f-string multi-line معقدة)
        parts = []
        parts.append(title)
        parts.append("")
        parts.append("📋 *التفاصيل:*")
        parts.append(str(details))
        parts.append("")
        parts.append("━━━━━━━━━━━━━━━━")
        parts.append("🔗 *URL:*")
        parts.append("`" + str(info.get("url", "N/A"))[:200] + "`")
        parts.append("")
        parts.append("📄 *عنوان الصفحة:*")
        parts.append("`" + str(info.get("title", "N/A"))[:100] + "`")
        parts.append("")
        parts.append("📝 *نص الصفحة:*")
        parts.append("```")
        parts.append(str(info.get("text", ""))[:500])
        parts.append("```")
        parts.append("")
        parts.append("🔘 *الأزرار:*")

        for b in info.get("buttons", [])[:15]:
            txt = b.get("text", "")[:50]
            bg = b.get("bg", "")
            parts.append(f"  • `{txt}` — bg: `{bg}`")

        parts.append("")
        parts.append("📝 *Inputs:*")
        for i in info.get("inputs", [])[:10]:
            parts.append(f"  • type=`{i.get('type', '')}` name=`{i.get('name', '')}` id=`{i.get('id', '')}`")

        parts.append("")
        parts.append("☑️ *Checkboxes:*")
        for c in info.get("checkboxes", [])[:5]:
            parts.append(f"  • name=`{c.get('name', '')}` checked=`{c.get('checked', '')}`")

        parts.append("")
        parts.append(f"🖼️ *Images:* {info.get('images', [])}")
        parts.append(f"🖼️ *iframes:* {info.get('iframes', 0)}")

        msg = "\n".join(parts)

        # ✅ نرسل للمستخدم
        if self.sender:
            try:
                await self.sender.reply_text(msg[:4000], parse_mode="Markdown")
            except Exception:
                try:
                    await self.sender.reply_text(msg[:4000])
                except Exception:
                    pass

        raise RuntimeError(f"{title}\n{details}")

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

    async def _has_wrong_password(self, page) -> bool:
        try:
            c = (await page.content()).lower()
            return 'incorrect password' in c or 'wrong password' in c
        except Exception:
            return False

    async def _do_signin(self, page) -> str:
        await self._send_shot(page, "📸 قبل sign in")

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
            return "ما قدرناش نكتب email"

        await self._click_next(page, "email")
        await human_delay(5, 8)

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
            return "ما لقيناش password"

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
