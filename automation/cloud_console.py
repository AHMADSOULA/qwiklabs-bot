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

        # ✅ إرسال Screenshot أولي
        await self._send_shot(page, "📸 فتح Cloud Console")

        for step in range(10):
            self.step_count = step + 1
            log.info(f"═══ خطوة {step + 1}/10 ═══")
            await human_delay(2, 3)
            await take_screenshot(page, f"cc_step_{step}")
            log.info(f"URL: {page.url[:120]}")

            # ✅ 1. Console ready?
            if await self._is_console_ready(page):
                log.info("✅ Console ready!")
                await self._send_shot(page, "✅ دخل لـ Cloud Console")
                await human_delay(3, 5)
                return page

            # ✅ 2. Speedbump / TOS / Welcome
            if await self._is_speedbump_or_tos(page):
                log.info("📋 Speedbump/TOS")
                await self._send_shot(page, "📋 صفحة Terms of Service")

                handled = await self._handle_speedbump(page)
                if handled:
                    log.info("✅ TOS processed")
                    await self._send_shot(page, "✅ ضغطنا على Accept")
                    await human_delay(10, 15)
                    continue
                else:
                    await self._send_shot(page, "❌ ما قدرناش نضغط Accept")
                    await self._raise_problem(
                        page,
                        "🔴 فشل التعامل مع Speedbump/TOS",
                        "الصفحة طلبت Terms of Service، ولكن ما قدرناش نضغط"
                    )

            # ✅ 3. CAPTCHA
            try:
                from automation.captcha_solver import has_captcha, detect_and_solve_captcha
                if await has_captcha(page):
                    log.info("🚨 CAPTCHA")
                    # 📸 نرسل صورة CAPTCHA
                    await self._send_shot(page, "🚨 CAPTCHA مطلوبة")

                    if self.captcha_count >= 3:
                        await self._raise_problem(
                            page,
                            "🔴 CAPTCHA متكررة (3 مرات)",
                            "Google كتطلب CAPTCHA بزاف"
                        )
                    solution = await detect_and_solve_captcha(
                        page, user_id=self.user_id, sender=self.sender
                    )
                    if solution:
                        self.captcha_count += 1
                        await self._send_shot(page, f"✅ CAPTCHA solved: {solution}")
                        await human_delay(5, 8)
                        continue
                    else:
                        await self._raise_problem(
                            page,
                            "🔴 CAPTCHA ما تحلّتش",
                            "ما قدرناش نحلو CAPTCHA"
                        )
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
                        await self._raise_problem(
                            page,
                            f"🔴 Sign in فشل: {result}",
                            "ما قدرناش نكمل تسجيل الدخول"
                        )
                except Exception as e:
                    await self._raise_problem(page, "🔴 Sign in exception", str(e)[:300])

            # ✅ 5. Verify?
            if await self._has_verify(page):
                await self._send_shot(page, "🔴 Google كتطلب verify")
                await self._raise_problem(
                    page,
                    "🔴 Google كتطلب verify (2FA)",
                    "Google كتطلب تأكيد الهاتف/الإيميل"
                )

            # ✅ 6. كلمة سر غلط؟
            if await self._has_wrong_password(page):
                await self._send_shot(page, "🔴 كلمة السر غلط")
                await self._raise_problem(
                    page,
                    "🔴 كلمة السر غلط",
                    "Google رفضت كلمة السر"
                )

            # ✅ 7. صفحة غير معروفة
            log.warning(f"❓ صفحة: {page.url[:100]}")
            await human_delay(5, 8)

        await self._raise_problem(
            page,
            "🔴 فشل بعد 10 خطوات",
            f"URL: {page.url[:200]}"
        )

    # ==================== Send Screenshot ====================

    async def _send_shot(self, page, caption: str = ""):
        """ياخد Screenshot ويرسلو للبوت"""
        try:
            from utils.screenshot import take_screenshot
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
                    log.warning(f"فشل إرسال صورة: {e}")
        except Exception as e:
            log.warning(f"_send_shot: {e}")

    # ==================== Raise Problem ====================

    async def _raise_problem(self, page, title: str, details: str):
        log.error(f"❌ {title}: {details}")
        await self._send_shot(page, f"{title}\n{details[:200]}")

        info = await self._collect_problem_info(page)
        msg = f"""{title}

📋 *التفاصيل:*
{details}

🔗 *URL:*
`{info.get('url', 'N/A')[:200]}`

📄 *نص:*
{info.get('text', '')[:300]}

🔘 *أزرار:*
{info.get('buttons', [])}

☑️ *Checkboxes:*
{info.get('checkboxes', [])}
"""
        if self.sender:
            try:
                await self.sender.reply_text(msg[:4000], parse_mode="Markdown")
            except Exception:
                await self.sender.reply_text(msg[:4000])

        raise RuntimeError(f"{title}\n{details}")

    async def _collect_problem_info(self, page) -> dict:
        try:
            return await page.evaluate("""
                () => {
                    const r = {
                        url: window.location.href.substring(0, 250),
                        text: (document.body.innerText || '').substring(0, 400).replace(/\\n+/g, ' | '),
                        buttons: [],
                        checkboxes: [],
                    };
                    for (const b of document.querySelectorAll('button, a[role="button"], input[type="submit"]')) {
                        if (b.offsetParent === null) continue;
                        const t = (b.innerText || b.value || '').trim();
                        if (t && t.length < 60) r.buttons.push(t);
                    }
                    for (const cb of document.querySelectorAll('input[type="checkbox"]')) {
                        if (cb.offsetParent === null) continue;
                        r.checkboxes.push({name: cb.name || '', checked: cb.checked});
                    }
                    return r;
                }
            """)
        except Exception as e:
            return {"error": str(e)}

    # ==================== Speedbump / TOS ====================

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
        await human_delay(5, 8)

        try:
            info = await page.evaluate("""
                () => {
                    const r = { buttons: [], checkboxes: [], selects: [] };
                    for (const b of document.querySelectorAll('button, a[role="button"], input[type="submit"]')) {
                        if (b.offsetParent === null) continue;
                        const t = (b.innerText || b.value || '').trim();
                        if (t && t.length < 100) r.buttons.push({text: t.substring(0, 60)});
                    }
                    for (const cb of document.querySelectorAll('input[type="checkbox"]')) {
                        if (cb.offsetParent === null) continue;
                        r.checkboxes.push({name: cb.name, checked: cb.checked});
                    }
                    for (const s of document.querySelectorAll('select')) {
                        if (s.offsetParent === null) continue;
                        r.selects.push({name: s.name, value: s.value});
                    }
                    return r;
                }
            """)
            log.info(f"📋 Buttons: {info.get('buttons')}")
        except Exception:
            pass

        # Country
        try:
            sel = page.locator('select').first
            if await sel.count() > 0 and await sel.is_visible():
                current = await sel.input_value()
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
        except Exception:
            pass

        await human_delay(3, 5)

        # ✅ 5 طرق للضغط
        for method in range(1, 6):
            log.info(f"🔘 طريقة {method}/5")

            try:
                clicked = await page.evaluate("""
                    async () => {
                        const sleep = (ms) => new Promise(r => setTimeout(r, ms));
                        const kws = ['accept', 'i accept', 'continue', 'agree', 'i agree',
                                     'submit', 'ok', 'yes', 'understood', 'got it'];
                        const all = document.querySelectorAll('button, a, [role="button"], input[type="submit"]');
                        for (const el of all) {
                            if (el.offsetParent === null || el.disabled) continue;
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
                                    return { clicked: t, method: 'exact' };
                                }
                            }
                        }
                        return null;
                    }
                """)
                if clicked:
                    log.info(f"✅ طريقة {method}: {clicked}")
                    await human_delay(5, 8)
                    return True
            except Exception as e:
                log.warning(f"طريقة {method}: {e}")

            # Blue button
            try:
                clicked = await page.evaluate("""
                    async () => {
                        const sleep = (ms) => new Promise(r => setTimeout(r, ms));
                        for (const el of document.querySelectorAll('button, input[type="submit"]')) {
                            if (el.offsetParent === null || el.disabled) continue;
                            const bg = window.getComputedStyle(el).backgroundColor;
                            if (bg === 'rgb(26, 115, 232)' || bg === 'rgb(66, 133, 244)' ||
                                bg === 'rgb(23, 78, 166)' || bg === 'rgb(21, 101, 192)') {
                                el.scrollIntoView({block: 'center'});
                                el.focus();
                                await sleep(300);
                                el.click();
                                return { text: (el.innerText || '').substring(0, 50), bg };
                            }
                        }
                        return null;
                    }
                """)
                if clicked:
                    log.info(f"✅ Blue button: {clicked}")
                    await human_delay(5, 8)
                    return True
            except Exception:
                pass

            # Playwright
            for sel in [
                'button:has-text("Accept")',
                'button:has-text("I accept")',
                'button:has-text("Continue")',
                'button:has-text("Agree")',
                'button:has-text("I agree")',
            ]:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0 and await el.is_visible():
                        log.info(f"✅ Playwright: {sel}")
                        try:
                            await el.click(timeout=3000)
                        except Exception:
                            await el.click(force=True, timeout=3000)
                        await human_delay(5, 8)
                        return True
                except Exception:
                    continue

            # Last button
            try:
                clicked = await page.evaluate("""
                    () => {
                        const all = document.querySelectorAll('button, input[type="submit"]');
                        const v = Array.from(all).filter(b => b.offsetParent !== null && !b.disabled);
                        if (v.length > 0) {
                            const last = v[v.length - 1];
                            last.click();
                            return { clicked: 'last', text: (last.innerText || '').substring(0, 50) };
                        }
                        return null;
                    }
                """)
                if clicked:
                    log.info(f"✅ Last button: {clicked}")
                    await human_delay(5, 8)
                    return True
            except Exception:
                pass

            await human_delay(2, 3)

        return False

    # ==================== Sign In ====================

    async def _do_signin(self, page) -> str:
        await self._send_shot(page, "📸 قبل تسجيل الدخول")

        # ========== EMAIL ==========
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

        await self._send_shot(page, f"📸 كتبنا email: {self.username}")
        await self._click_next(page, "email")
        await human_delay(5, 8)
        await self._send_shot(page, "📸 بعد email Next")

        # ✅ CAPTCHA بعد email
        try:
            from automation.captcha_solver import has_captcha, detect_and_solve_captcha
            if await has_captcha(page):
                await self._send_shot(page, "🚨 CAPTCHA بعد email")
                solution = await detect_and_solve_captcha(page, user_id=self.user_id, sender=self.sender)
                if solution:
                    self.captcha_count += 1
                    await self._send_shot(page, f"✅ CAPTCHA: {solution}")
                    await human_delay(5, 8)
        except Exception:
            pass

        # ========== PASSWORD ==========
        await human_delay(3, 5)
        await self._send_shot(page, "📸 قبل كلمة السر")

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

        await self._send_shot(page, "📸 كتبنا password")
        await self._click_next(page, "password")
        await human_delay(8, 12)
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
