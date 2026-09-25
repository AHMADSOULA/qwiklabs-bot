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
        self.step_count = 0

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

        # ✅ حلقة قصيرة: 10 خطوات كحد أقصى
        for step in range(10):
            self.step_count = step + 1
            log.info(f"═══ خطوة {step + 1}/10 ═══")
            await human_delay(2, 3)
            await take_screenshot(page, f"cc_step_{step}")
            log.info(f"URL: {page.url[:120]}")

            # ✅ 1. Console ready?
            if await self._is_console_ready(page):
                log.info("✅ Console ready!")
                await human_delay(3, 5)
                return page

            # ✅ 2. Speedbump / TOS
            if await self._is_speedbump_or_tos(page):
                log.info("📋 Speedbump/TOS")
                handled = await self._handle_speedbump(page)
                if handled:
                    log.info("✅ TOS processed")
                    await human_delay(10, 15)
                    continue
                else:
                    # ❌ ما قدرناش → توقف
                    await self._raise_problem(
                        page,
                        "🔴 فشل التعامل مع Speedbump/TOS",
                        "الصفحة طلبت Terms of Service، ولكن ما قدرناش نضغط على checkbox/continue"
                    )

            # ✅ 3. CAPTCHA
            try:
                from automation.captcha_solver import has_captcha, detect_and_solve_captcha
                if await has_captcha(page):
                    if self.captcha_count >= 3:
                        await self._raise_problem(
                            page,
                            "🔴 CAPTCHA متكررة (3 مرات)",
                            "Google كتطلب CAPTCHA بزاف — يمكن IP مشبوه"
                        )
                    log.info("🚨 CAPTCHA")
                    solution = await detect_and_solve_captcha(
                        page, user_id=self.user_id, sender=self.sender
                    )
                    if solution:
                        self.captcha_count += 1
                        await human_delay(5, 8)
                        continue
                    else:
                        await self._raise_problem(
                            page,
                            "🔴 CAPTCHA ما تحلّتش",
                            "ما قدرناش نحلو CAPTCHA (يدوي/TrueCaptcha)"
                        )
            except Exception as e:
                log.warning(f"CAPTCHA: {e}")

            # ✅ 4. Sign in?
            if await self._is_signin(page):
                log.info("🔑 Sign in")
                try:
                    result = await self._do_signin(page)
                    if result == "ok":
                        await human_delay(6, 10)
                        continue
                    else:
                        await self._raise_problem(
                            page,
                            f"🔴 Sign in فشل: {result}",
                            "ما قدرناش نكمل تسجيل الدخول"
                        )
                except Exception as e:
                    await self._raise_problem(
                        page,
                        "🔴 Sign in exception",
                        str(e)[:300]
                    )

            # ✅ 5. Verify?
            if await self._has_verify(page):
                await self._raise_problem(
                    page,
                    "🔴 Google كتطلب verify (2FA)",
                    "Google كتطلب تأكيد الهاتف/الإيميل — الحل: تسجيل يدوي أول مرة"
                )

            # ✅ 6. كلمة سر غلط؟
            if await self._has_wrong_password(page):
                await self._raise_problem(
                    page,
                    "🔴 كلمة السر غلط",
                    "Google رفضت كلمة السر — جدد الرابط من Skills"
                )

            # ✅ 7. صفحة غير معروفة → نستنى مرة
            log.warning(f"❓ صفحة: {page.url[:100]}")
            await human_delay(5, 8)

        # ❌ انتهت 10 خطوات بلا نتيجة
        await self._raise_problem(
            page,
            "🔴 فشل بعد 10 خطوات",
            f"البوت ما قدرش يوصل للـ Console\nURL: {page.url[:200]}"
        )

    # ==================== Raise Problem (توقف + تقرير) ====================

    async def _raise_problem(self, page, title: str, details: str):
        """
        يتوقف فوراً ويرسل تقرير كامل.
        """
        log.error(f"❌ {title}: {details}")

        # 📸 Screenshot أخير
        shot = await take_screenshot(page, "problem")

        # ✅ نجمع كل المعلومات
        info = await self._collect_problem_info(page)

        # ✅ نبني رسالة
        msg = f"""{title}

📋 *التفاصيل:*
{details}

🔗 *URL:*
`{info.get('url', 'N/A')[:200]}`

📄 *نص الصفحة:*
{info.get('text', '')[:300]}

🔘 *الأزرار:*
{info.get('buttons', [])}

☑️ *Checkboxes:*
{info.get('checkboxes', [])}

📝 *Inputs:*
{info.get('inputs', [])}

🖼️ *Images:*
{info.get('images', [])}

⏱️ *الخطوات اللي تمت:* {self.step_count}/10
🔄 *CAPTCHA:* {self.captcha_count}/3
"""

        # ✅ نرسل للمستخدم
        if self.sender:
            try:
                await self.sender.reply_text(msg[:4000], parse_mode="Markdown")
            except Exception:
                await self.sender.reply_text(msg[:4000])

            # 📸 نرسل الصورة
            if shot:
                try:
                    from telegram import InputFile
                    with open(shot, "rb") as f:
                        await self.sender.reply_photo(
                            photo=InputFile(f),
                            caption=f"📸 {title}"
                        )
                except Exception:
                    pass

        # ✅ نرفع exception
        raise RuntimeError(f"{title}\n{details}")

    async def _collect_problem_info(self, page) -> dict:
        """يجمع كل المعلومات عن المشكل"""
        try:
            return await page.evaluate("""
                () => {
                    const r = {
                        url: window.location.href.substring(0, 250),
                        title: document.title || '',
                        text: (document.body.innerText || '').substring(0, 400).replace(/\\n+/g, ' | '),
                        buttons: [],
                        checkboxes: [],
                        inputs: [],
                        images: [],
                    };
                    // Buttons
                    for (const b of document.querySelectorAll('button, a[role="button"], input[type="submit"]')) {
                        if (b.offsetParent === null) continue;
                        const t = (b.innerText || b.value || '').trim();
                        if (t && t.length < 60) r.buttons.push(t);
                    }
                    // Checkboxes
                    for (const cb of document.querySelectorAll('input[type="checkbox"]')) {
                        if (cb.offsetParent === null) continue;
                        r.checkboxes.push({
                            name: cb.name || '',
                            id: cb.id || '',
                            checked: cb.checked,
                        });
                    }
                    // Inputs
                    for (const inp of document.querySelectorAll('input')) {
                        if (inp.offsetParent === null) continue;
                        r.inputs.push({
                            type: inp.type || '',
                            name: inp.name || '',
                            id: inp.id || '',
                        });
                    }
                    // Images
                    for (const img of document.querySelectorAll('img')) {
                        if (img.offsetParent === null) continue;
                        const s = (img.src || '').toLowerCase();
                        if (s.includes('captcha')) {
                            r.images.push('CAPTCHA');
                        } else if (s.length > 0) {
                            r.images.push(s.substring(0, 50));
                        }
                    }
                    return r;
                }
            """)
        except Exception as e:
            return {"error": str(e)}

    # ==================== Helpers ====================

    async def _has_wrong_password(self, page) -> bool:
        try:
            c = (await page.content()).lower()
            return 'incorrect password' in c or 'wrong password' in c
        except Exception:
            return False

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

    async def _handle_speedbump(self, page) -> bool:
        log.info("🔍 نحلل صفحة Speedbump...")

        # Country
        try:
            sel = page.locator('select').first
            if await sel.count() > 0 and await sel.is_visible():
                current = await sel.input_value()
                log.info(f"🌍 Country: {current}")
                if not current:
                    try:
                        await sel.select_option(label="United States")
                    except Exception:
                        pass
                    await human_delay(1, 2)
        except Exception:
            pass

        # Checkbox
        try:
            result = await page.evaluate("""
                () => {
                    for (const cb of document.querySelectorAll('input[type="checkbox"]')) {
                        if (cb.offsetParent === null) continue;
                        if (cb.checked) return { already: true };
                        cb.scrollIntoView({block: 'center'});
                        cb.focus();
                        const lb = cb.closest('label');
                        if (lb) lb.click(); else cb.click();
                        cb.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                        cb.dispatchEvent(new Event('change', { bubbles: true }));
                        return { checked: cb.checked };
                    }
                    return null;
                }
            """)
            if result:
                log.info(f"✅ checkbox: {result}")
                await human_delay(2, 3)
        except Exception as e:
            log.warning(f"checkbox: {e}")

        # Continue
        await human_delay(2, 3)
        try:
            clicked = await page.evaluate("""
                async () => {
                    const sleep = (ms) => new Promise(r => setTimeout(r, ms));
                    const kws = ['continue', 'agree', 'accept', 'submit', 'ok', 'yes', 'i agree'];
                    for (const el of document.querySelectorAll('button, a, [role="button"], input[type="submit"]')) {
                        if (el.offsetParent === null) continue;
                        if (el.disabled) continue;
                        const t = (el.innerText || el.value || '').trim().toLowerCase();
                        if (!t || t.length > 100) continue;
                        for (const kw of kws) {
                            if (t === kw || t.includes(kw)) {
                                el.scrollIntoView({block: 'center'});
                                el.focus();
                                await sleep(300);
                                el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
                                el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                                el.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }));
                                el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                                el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                                el.click();
                                return { clicked: t.substring(0, 50) };
                            }
                        }
                    }
                    return null;
                }
            """)
            if clicked:
                log.info(f"✅ continue: {clicked}")
                await human_delay(5, 8)
                return True
        except Exception as e:
            log.warning(f"continue: {e}")

        return False

    async def _do_signin(self, page) -> str:
        """يرجع 'ok' أو سبب الفشل"""
        await take_screenshot(page, "cc_before_signin")

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
            return "ما قدرناش نكتب email"

        await self._click_next(page, "email")
        await human_delay(5, 8)
        await take_screenshot(page, "cc_after_email")

        # CAPTCHA بعد email
        try:
            from automation.captcha_solver import has_captcha, detect_and_solve_captcha
            if await has_captcha(page) and self.captcha_count < 3:
                solution = await detect_and_solve_captcha(page, user_id=self.user_id, sender=self.sender)
                if solution:
                    self.captcha_count += 1
                    await human_delay(5, 8)
                else:
                    return "CAPTCHA بعد email ما تحلّتش"
        except Exception:
            pass

        # PASSWORD
        await human_delay(3, 5)
        await take_screenshot(page, "cc_before_pwd")

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
            return "ما لقيناش/ما قدرناش نكتب حقل password بعد email"

        await self._click_next(page, "password")
        await human_delay(8, 12)
        await take_screenshot(page, "cc_after_pwd")
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
