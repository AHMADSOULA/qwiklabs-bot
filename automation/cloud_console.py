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

                url_before = page.url

                # ✅ نضغط على "I understand" بنفس طريقة "Next"
                clicked = await self._click_i_understand_like_next(page)

                if clicked:
                    log.info("✅ ضغطنا I understand — ننتظر")
                    changed = await self._wait_for_url_change(page, url_before, timeout=15)
                    if changed:
                        log.info("🎉 خرجنا من TOS")
                        await self._send_shot(page, "🎉 خرجنا من TOS")
                        await human_delay(8, 12)
                        continue
                    else:
                        log.warning("⚠️ ما تبدلش — نضغطو مرة أخرى")
                        await self._send_shot(page, "⚠️ ما تبدلش — نعاود")
                        # ✅ نحاول مرة أخرى بعد 5 ثواني
                        await human_delay(5, 8)
                        clicked2 = await self._click_i_understand_like_next(page)
                        if clicked2:
                            changed2 = await self._wait_for_url_change(page, url_before, timeout=15)
                            if changed2:
                                log.info("🎉 خرجنا من TOS (محاولة 2)")
                                await human_delay(8, 12)
                                continue
                        await human_delay(5, 8)
                        continue
                else:
                    await self._raise_problem(
                        page,
                        "🔴 ما قدرناش نضغط I understand",
                        "الصفحة فيها TOS ولكن زر I understand ما لقيناهش"
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

        await self._raise_problem(page, "🔴 فشل بعد 15 خطوة", f"URL: {page.url[:200]}")

    # ==================== Click I Understand (نفس طريقة Next) ====================

    async def _click_i_understand_like_next(self, page) -> bool:
        """
        يضغط على "I understand" بنفس طريقة Playwright (كيما Next).
        """
        log.info("🔍 نبحث عن زر 'I understand'...")

        # ✅ 1. نسجل الأزرار
        try:
            buttons = await page.evaluate("""
                () => {
                    const r = [];
                    for (const el of document.querySelectorAll('button, a, input[type="submit"], [role="button"]')) {
                        if (el.offsetParent === null) continue;
                        const rect = el.getBoundingClientRect();
                        const bg = window.getComputedStyle(el).backgroundColor;
                        const t = (el.innerText || el.value || '').trim();
                        r.push({
                            text: t.substring(0, 80),
                            tag: el.tagName,
                            bg: bg,
                            x: rect.x + rect.width / 2,
                            y: rect.y + rect.height / 2,
                        });
                    }
                    return r;
                }
            """)
            log.info(f"📋 الأزرار: {buttons}")
        except Exception as e:
            log.warning(f"فشل: {e}")

        # ✅ 2. Playwright locator — نفس طريقة Next
        for sel in [
            'button:has-text("I understand")',
            'button:has-text("Understand")',
            'button:has-text("I agree")',
            'button:has-text("Accept")',
            'button:has-text("Continue")',
            'a:has-text("I understand")',
            '[role="button"]:has-text("I understand")',
            'button[type="submit"]',
        ]:
            try:
                el = page.locator(sel).first
                cnt = await el.count()
                if cnt == 0:
                    continue
                if not await el.is_visible():
                    continue

                log.info(f"✅ Playwright: {sel}")

                # ✅ نفس طريقة Next
                await el.scroll_into_view_if_needed()
                await human_delay(0.3, 0.6)

                try:
                    await el.click(timeout=5000)
                    log.info(f"✅ click عادي نجح")
                    return True
                except Exception as e1:
                    log.warning(f"click عادي فشل: {e1}")

                try:
                    await el.click(force=True, timeout=5000)
                    log.info(f"✅ click force نجح")
                    return True
                except Exception as e2:
                    log.warning(f"force فشل: {e2}")

                try:
                    await el.dispatch_event("click")
                    log.info(f"✅ dispatch_event نجح")
                    return True
                except Exception as e3:
                    log.warning(f"dispatch_event فشل: {e3}")
            except Exception:
                continue

        # ✅ 3. Playwright mouse click بالإحداثيات
        try:
            btn = await page.evaluate("""
                () => {
                    for (const el of document.querySelectorAll('button, a, input[type="submit"], [role="button"]')) {
                        if (el.offsetParent === null) continue;
                        const t = (el.innerText || el.value || '').trim().toLowerCase();
                        if (t === 'i understand' || t.includes('understand')) {
                            const rect = el.getBoundingClientRect();
                            return {
                                x: rect.x + rect.width / 2,
                                y: rect.y + rect.height / 2,
                                text: t,
                            };
                        }
                    }
                    // ✅ زر أزرق
                    for (const el of document.querySelectorAll('button, input[type="submit"], [role="button"]')) {
                        if (el.offsetParent === null) continue;
                        const bg = window.getComputedStyle(el).backgroundColor;
                        if (bg.includes('11, 87') || bg.includes('26, 115') || bg.includes('66, 133')) {
                            const rect = el.getBoundingClientRect();
                            return {
                                x: rect.x + rect.width / 2,
                                y: rect.y + rect.height / 2,
                                text: (el.innerText || '').substring(0, 50),
                            };
                        }
                    }
                    return null;
                }
            """)
            if btn and btn.get("x", 0) > 0:
                log.info(f"🖱️ mouse click على: {btn.get('text')} فـ ({btn['x']}, {btn['y']})")
                await page.mouse.move(btn["x"], btn["y"], steps=15)
                await human_delay(0.5, 1)
                await page.mouse.down()
                await human_delay(0.15, 0.3)
                await page.mouse.up()
                await human_delay(5, 8)
                return True
        except Exception as e:
            log.warning(f"mouse: {e}")

        # ✅ 4. JS click
        try:
            clicked = await page.evaluate("""
                () => {
                    for (const el of document.querySelectorAll('button, a, input[type="submit"], [role="button"]')) {
                        if (el.offsetParent === null || el.disabled) continue;
                        const t = (el.innerText || el.value || '').trim().toLowerCase();
                        if (t === 'i understand' || t.includes('understand')) {
                            el.click();
                            return { text: t, method: 'understand' };
                        }
                    }
                    return null;
                }
            """)
            if clicked:
                log.info(f"✅ JS click: {clicked}")
                await human_delay(5, 8)
                return True
        except Exception:
            pass

        return False

    # ==================== Wait for URL Change ====================

    async def _wait_for_url_change(self, page, url_before: str, timeout: int = 15) -> bool:
        log.info(f"⏳ ننتظر URL يتغير...")
        for i in range(timeout):
            await asyncio.sleep(1)
            if page.url != url_before:
                log.info(f"✅ URL تبدل")
                return True
            # ✅ نتحقق واش الزر اختفى
            try:
                has_btn = await page.evaluate("""
                    () => {
                        for (const el of document.querySelectorAll('button, [role="button"]')) {
                            if (el.offsetParent === null) continue;
                            const t = (el.innerText || '').trim().toLowerCase();
                            if (t.includes('understand')) return true;
                        }
                        return false;
                    }
                """)
                if not has_btn:
                    log.info("✅ الزر اختفى — الصفحة تبدلت")
                    return True
            except Exception:
                pass
        return False

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
