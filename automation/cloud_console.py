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

            # ✅ 2. Speedbump / TOS
            if await self._is_speedbump_or_tos(page):
                log.info("📋 صفحة TOS")
                await self._send_shot(page, "📋 صفحة Terms of Service")

                # ✅ نحفظ URL قبل الضغط
                url_before = page.url

                handled = await self._handle_speedbump(page, url_before)
                if handled:
                    log.info("✅ ضغط Accept — ننتظر تغيير الصفحة...")
                    # ✅ ننتظر الصفحة تبدل (URL أو DOM)
                    changed = await self._wait_for_url_change(page, url_before, timeout=15)
                    if changed:
                        log.info("🎉 الصفحة تبدلت!")
                        await self._send_shot(page, "🎉 خرجنا من TOS")
                        await human_delay(8, 12)
                        continue
                    else:
                        log.warning("⚠️ الصفحة ما تبدلتش — نعاودو")
                        await self._send_shot(page, "⚠️ ما تبدلش — نعاود")
                        await human_delay(3, 5)
                        # ✅ نحاول مرة أخرى بطريقة مختلفة
                        await self._force_click_blue_button(page)
                        await human_delay(5, 8)
                        continue
                else:
                    await self._raise_problem(
                        page,
                        "🔴 ما لقيناش زر Accept",
                        "الصفحة فيها Terms of Service ولكن ما لقيناش زر"
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

    # ==================== Wait for URL Change ====================

    async def _wait_for_url_change(self, page, url_before: str, timeout: int = 15) -> bool:
        """ينتظر URL يتغير"""
        log.info(f"⏳ ننتظر URL يتغير من: {url_before[:80]}")
        for i in range(timeout):
            await asyncio.sleep(1)
            new_url = page.url
            if new_url != url_before:
                log.info(f"✅ URL تبدل: {new_url[:80]}")
                return True
        return False

    # ==================== Force Click Blue Button ====================

    async def _force_click_blue_button(self, page) -> bool:
        """
        يضغط على الزر الأزرق بـ Playwright مباشرة (ماشي JS).
        """
        log.info("🔵 نحاول نضغط الزر الأزرق بـ Playwright...")

        # ✅ 1. دور على الزر الأزرق عبر JS (نجيب معلومات)
        try:
            buttons = await page.evaluate("""
                () => {
                    const result = [];
                    for (const el of document.querySelectorAll('button, a, input[type="submit"], [role="button"]')) {
                        if (el.offsetParent === null || el.disabled) continue;
                        const bg = window.getComputedStyle(el).backgroundColor;
                        const is_blue = (
                            bg === 'rgb(26, 115, 232)' ||
                            bg === 'rgb(66, 133, 244)' ||
                            bg === 'rgb(23, 78, 166)' ||
                            bg === 'rgb(21, 101, 192)' ||
                            bg === 'rgb(13, 101, 45)' ||
                            bg === 'rgb(24, 90, 188)' ||
                            bg === 'rgb(0, 123, 255)' ||
                            bg.includes('26, 115') ||
                            bg.includes('66, 133')
                        );
                        if (is_blue) {
                            const rect = el.getBoundingClientRect();
                            result.push({
                                text: (el.innerText || el.value || '').trim().substring(0, 50),
                                tag: el.tagName,
                                bg: bg,
                                x: rect.x + rect.width / 2,
                                y: rect.y + rect.height / 2,
                                w: rect.width,
                                h: rect.height,
                            });
                        }
                    }
                    return result;
                }
            """)
            log.info(f"🔵 أزرار زرقاء: {buttons}")
        except Exception as e:
            log.warning(f"فشل جلب أزرار: {e}")
            buttons = []

        # ✅ 2. Playwright click (بالإحداثيات)
        for btn in buttons:
            try:
                x = btn.get("x", 0)
                y = btn.get("y", 0)
                if x <= 0 or y <= 0:
                    continue

                log.info(f"🎯 Playwright click على ({x}, {y}) — {btn.get('text')}")

                # ✅ طريقة 1: page.mouse.click
                await page.mouse.move(x, y, steps=10)
                await human_delay(0.3, 0.5)
                await page.mouse.down()
                await human_delay(0.1, 0.2)
                await page.mouse.up()
                await human_delay(3, 5)

                return True
            except Exception as e:
                log.warning(f"mouse click فشل: {e}")
                continue

        # ✅ 3. Playwright locator
        for sel in [
            'button:has-text("Accept")',
            'button:has-text("I accept")',
            'button:has-text("Continue")',
            'button:has-text("Agree")',
            'button:has-text("I agree")',
            'button[type="submit"]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    log.info(f"✅ Playwright locator: {sel}")
                    await el.scroll_into_view_if_needed()
                    await human_delay(0.3, 0.5)
                    await el.click(timeout=5000)
                    await human_delay(3, 5)
                    return True
            except Exception as e:
                log.warning(f"{sel}: {e}")
                continue

        return False

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

    async def _handle_speedbump(self, page, url_before: str) -> bool:
        log.info("🔍 نحلل صفحة TOS...")
        await human_delay(5, 8)

        # ✅ نسجل الأزرار
        try:
            info = await page.evaluate("""
                () => {
                    const r = { buttons: [], checkboxes: [], selects: [] };
                    for (const b of document.querySelectorAll('button, a, input[type="submit"], [role="button"]')) {
                        if (b.offsetParent === null) continue;
                        const t = (b.innerText || b.value || '').trim();
                        const bg = window.getComputedStyle(b).backgroundColor;
                        if (t && t.length < 100) r.buttons.push({text: t.substring(0, 60), bg: bg});
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
            log.info(f"📋 Checkboxes: {info.get('checkboxes')}")
            log.info(f"📋 Selects: {info.get('selects')}")
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

        # ✅ نضغط على الزر الأزرق
        return await self._force_click_blue_button(page)

    # ==================== Sign In ====================

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
            return "ما قدرناش نكتب email"

        await self._send_shot(page, f"📸 كتبنا email")
        await self._click_next(page, "email")
        await human_delay(5, 8)
        await self._send_shot(page, "📸 بعد email")

        # CAPTCHA
        try:
            from automation.captcha_solver import has_captcha, detect_and_solve_captcha
            if await has_captcha(page):
                await self._send_shot(page, "🚨 CAPTCHA")
                solution = await detect_and_solve_captcha(page, user_id=self.user_id, sender=self.sender)
                if solution:
                    self.captcha_count += 1
                    await self._send_shot(page, f"✅ CAPTCHA: {solution}")
                    await human_delay(5, 8)
        except Exception:
            pass

        # PASSWORD
        await human_delay(3, 5)
        await self._send_shot(page, "📸 قبل password")

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

    async def _raise_problem(self, page, title: str, details: str):
        log.error(f"❌ {title}: {details}")
        await self._send_shot(page, f"❌ {title}")

        info = {}
        try:
            info = await page.evaluate("""
                () => ({
                    url: window.location.href.substring(0, 250),
                    text: (document.body.innerText || '').substring(0, 400).replace(/\\n+/g, ' | '),
                })
            """)
        except Exception:
            pass

        msg = f"""{title}

📋 *التفاصيل:*
{details}

🔗 *URL:*
`{info.get('url', 'N/A')[:200]}`

📄 *نص:*
{info.get('text', '')[:300]}
"""
        if self.sender:
            try:
                await self.sender.reply_text(msg[:4000], parse_mode="Markdown")
            except Exception:
                await self.sender.reply_text(msg[:4000])

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
