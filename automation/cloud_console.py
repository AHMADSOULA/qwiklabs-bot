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

    async def login(self, username: str, password: str,
                    user_id: int = None, sender=None, context=None):
        self.username = username
        self.password = password
        self.user_id = user_id
        self.sender = sender

        page = await self.context.new_page()
        log.info("تسجيل الدخول...")

        await page.goto("https://console.cloud.google.com", wait_until="domcontentloaded")
        log.info("⏳ نستنى 10s...")
        await human_delay(10, 12)
        await take_screenshot(page, "cc_01_loaded")
        log.info(f"URL: {page.url}")

        try:
            for attempt in range(6):
                log.info(f"========== محاولة {attempt + 1} ==========")
                await human_delay(3, 5)
                await take_screenshot(page, f"cc_attempt_{attempt}")
                log.info(f"URL: {page.url}")

                # ✅ 1. Console ready?
                if await self._is_console_ready(page):
                    log.info("✅ وصلنا للـ Console!")
                    await human_delay(5, 8)
                    return page

                # ✅ 2. Welcome
                if await self._is_welcome_page(page):
                    log.info("📋 Welcome/TOS")
                    await human_delay(10, 12)
                    clicked = await self._handle_welcome_hard(page)
                    if clicked:
                        log.info("✅ ضغطنا — نستنى 20s")
                        await human_delay(20, 25)
                    else:
                        log.warning("⚠️ ما لقيناش Accept")
                        await human_delay(5, 8)
                    continue

                # ✅ 3. Sign in?
                if await self._is_signin_page(page):
                    log.info("🔑 Sign in")

                    from utils.diagnostic import analyze_page
                    analysis = await analyze_page(page)
                    log.info(f"📊 hasEmail: {analysis.get('hasEmail')}, hasPassword: {analysis.get('hasPassword')}, hasCaptcha: {analysis.get('hasCaptcha')}")

                    # CAPTCHA؟
                    if analysis.get("hasCaptcha"):
                        log.info("🚨 CAPTCHA detected")
                        try:
                            from automation.captcha_solver import detect_and_solve_captcha
                            solution = await detect_and_solve_captcha(
                                page,
                                user_id=user_id,
                                sender=sender,
                                context=context,
                            )
                            if solution:
                                log.info(f"✅ CAPTCHA solved: {solution}")
                                await self._fill_captcha(page, solution)
                                await human_delay(10, 12)
                                continue
                        except Exception as e:
                            log.warning(f"CAPTCHA: {e}")

                    result = await self._do_signin_with_analysis(page, attempt)
                    if result.get("success"):
                        log.info("✅ sign in نجح — نستنى 12s")
                        await human_delay(12, 15)
                        continue
                    else:
                        log.error(f"❌ sign in فشل: {result.get('reason')}")
                        raise RuntimeError(
                            f"❌ فشل تسجيل الدخول\n\n"
                            f"السبب: {result.get('reason')}\n"
                            f"تفاصيل: {result.get('details', '')}"
                        )

                # ✅ 4. Verify?
                if await self._has_verify_required(page):
                    await take_screenshot(page, f"cc_verify_{attempt}")
                    raise RuntimeError("❌ Google كتطلب verify")

                # ✅ 5. كلمة سر غلط؟
                if await self._has_wrong_password_error(page):
                    await take_screenshot(page, f"cc_wrong_pwd_{attempt}")
                    raise RuntimeError("❌ كلمة السر غلط")

                log.warning(f"❓ صفحة غير معروفة: {page.url[:100]}")
                await human_delay(10, 12)

            await take_screenshot(page, "cc_final_fail")
            raise RuntimeError(f"❌ فشل بعد 6 محاولات\nURL: {page.url[:200]}")

        except Exception as e:
            log.error(f"فشل: {e}")
            await take_screenshot(page, "cc_error")
            raise

    # ==================== الكتابة الحقيقية (keyboard) ====================

    async def _type_with_keyboard(self, page, el, value: str, field_name: str = "field") -> bool:
        """
        يكتب في الحقل باستعمال keyboard.type (حقيقي).
        """
        # ✅ 1. نضغط على الحقل
        try:
            await el.click()
            log.info(f"  🖱️ كليك على {field_name}")
            await human_delay(0.5, 1.0)
        except Exception as e:
            log.warning(f"  ⚠️ فشل click: {e}")

        # ✅ 2. نمسح أي محتوى موجود (Ctrl+A + Delete)
        try:
            await el.press("Control+a")
            await human_delay(0.2, 0.4)
            await el.press("Delete")
            await human_delay(0.3, 0.5)
            log.info(f"  🧹 مسحنا الحقل")
        except Exception as e:
            log.warning(f"  ⚠️ فشل مسح: {e}")

        # ✅ 3. نضغط مرة أخرى باش نتأكدو من focus
        try:
            await el.click()
            await human_delay(0.3, 0.5)
        except Exception:
            pass

        # ✅ 4. نكتب بـ keyboard.type (حقيقي)
        try:
            await page.keyboard.type(value, delay=80)
            log.info(f"  ⌨️ كتبنا بـ keyboard: '{value[:30]}'")
            await human_delay(1, 2)
        except Exception as e:
            log.warning(f"  ⚠️ فشل keyboard.type: {e}")
            return False

        # ✅ 5. نتحقق من القيمة
        try:
            val = await el.input_value()
            log.info(f"  📝 القيمة الحالية: '{val[:50]}'")
            if val.strip():
                log.info(f"  ✅ الكتابة نجحت ({field_name})")
                return True
            else:
                log.warning(f"  ⚠️ الحقل باقي فارغ!")
        except Exception as e:
            log.warning(f"  ⚠️ فشل قراءة القيمة: {e}")

        # ✅ 6. محاولة ثانية: JS مع dispatch events
        try:
            await el.evaluate("""(el, val) => {
                el.focus();
                el.value = '';
                for (const ch of val) {
                    el.value += ch;
                    el.dispatchEvent(new KeyboardEvent('keydown', {key: ch, bubbles: true}));
                    el.dispatchEvent(new KeyboardEvent('keypress', {key: ch, bubbles: true}));
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new KeyboardEvent('keyup', {key: ch, bubbles: true}));
                }
                el.dispatchEvent(new Event('change', {bubbles: true}));
            }""", value)
            await human_delay(1, 2)

            val = await el.input_value()
            log.info(f"  📝 [JS] القيمة: '{val[:50]}'")
            if val.strip():
                log.info(f"  ✅ الكتابة نجحت (JS)")
                return True
        except Exception as e:
            log.warning(f"  ⚠️ فشل JS: {e}")

        return False

    # ==================== Sign In ====================

    async def _do_signin_with_analysis(self, page, attempt: int) -> dict:
        await take_screenshot(page, f"cc_before_signin_{attempt}")

        # نسجل inputs
        try:
            inputs = await page.evaluate("""
                () => {
                    const all = document.querySelectorAll('input');
                    return Array.from(all).map((el, i) => ({
                        idx: i,
                        type: el.type || '',
                        name: el.name || '',
                        id: el.id || '',
                        autocomplete: el.autocomplete || '',
                        visible: el.offsetParent !== null,
                        value: (el.value || '').substring(0, 30),
                        placeholder: el.placeholder || '',
                    }));
                }
            """)
            log.info(f"📋 inputs: {inputs}")
        except Exception as e:
            log.warning(f"فشل: {e}")
            inputs = []

        # ============================================
        # ✅ EMAIL — keyboard.type
        # ============================================
        email_filled = False
        for sel in [
            'input[type="email"]',
            'input[type="text"][name="identifier"]',
            'input[name="identifier"]',
            'input[autocomplete="username"]',
        ]:
            try:
                el = page.locator(sel).first
                cnt = await el.count()
                if cnt == 0:
                    continue
                if not await el.is_visible():
                    continue

                log.info(f"✅ لقيت email field: {sel}")

                # ✅ نكتب بـ keyboard.type
                ok = await self._type_with_keyboard(page, el, self.username, "email")
                if ok:
                    email_filled = True
                    await human_delay(3, 5)
                    break
            except Exception as e:
                log.warning(f"فشل {sel}: {e}")
                continue

        if not email_filled:
            await take_screenshot(page, f"cc_email_fail_{attempt}")
            return {
                "success": False,
                "reason": "ما قدرتش نكتب الإيميل",
                "details": f"inputs: {[i['name'] or i['id'] or i['placeholder'] for i in inputs if i['visible']]}",
            }

        # ✅ نتحقق من القيمة النهائية
        try:
            el = page.locator('input[type="email"], input[name="identifier"]').first
            val = await el.input_value()
            log.info(f"✅ email النهائي: '{val}'")
        except Exception:
            pass

        # ✅ Next
        log.info("🖱️ نضغط Next (email)")
        if not await self._click_next_with_logs(page, "email"):
            return {"success": False, "reason": "ما لقيتش زر Next (email)"}

        await human_delay(10, 15)
        await take_screenshot(page, f"cc_after_email_next_{attempt}")

        # ✅ نتحقق من inputs الجديدة
        after_inputs = await page.evaluate("""
            () => {
                const all = document.querySelectorAll('input');
                return Array.from(all).map(el => ({
                    type: el.type || '',
                    name: el.name || '',
                    id: el.id || '',
                    visible: el.offsetParent !== null,
                    value: (el.value || '').substring(0, 30),
                }));
            }
        """)
        log.info(f"📋 inputs بعد Next: {after_inputs}")
        log.info(f"🔗 URL بعد Next: {page.url[:150]}")

        has_password = any(
            i.get("type") == "password" and i.get("visible")
            for i in after_inputs
        )

        # ============================================
        # ✅ إذا ما كاينش password → نعاود نجرب
        # ============================================
        if not has_password:
            current_url = page.url.lower()

            if "accounts.google.com" in current_url and "signin" in current_url:
                log.warning("⚠️ Google رجع Sign in — نعاود نكتب email")

                await human_delay(3, 5)
                for sel in [
                    'input[type="email"]',
                    'input[name="identifier"]',
                    'input[type="text"]',
                ]:
                    try:
                        el = page.locator(sel).first
                        if await el.count() == 0 or not await el.is_visible():
                            continue
                        log.info(f"✅ نعاود نكتب فـ: {sel}")
                        ok = await self._type_with_keyboard(page, el, self.username, "email-retry")
                        if ok:
                            await human_delay(3, 5)
                            await self._click_next_with_logs(page, "email-retry")
                            await human_delay(10, 15)
                            await take_screenshot(page, f"cc_retry_after_email_{attempt}")
                            break
                    except Exception:
                        continue

                after_inputs2 = await page.evaluate("""
                    () => {
                        const all = document.querySelectorAll('input');
                        return Array.from(all).map(el => ({
                            type: el.type || '',
                            name: el.name || '',
                            visible: el.offsetParent !== null,
                        }));
                    }
                """)
                log.info(f"📋 inputs بعد retry: {after_inputs2}")
                has_password = any(
                    i.get("type") == "password" and i.get("visible")
                    for i in after_inputs2
                )

        if not has_password:
            await take_screenshot(page, f"cc_no_pwd_field_{attempt}")
            return {
                "success": False,
                "reason": "ما لقيتش حقل password بعد email",
                "details": f"URL: {page.url[:150]}\n"
                          f"inputs: {[i['name'] or i['type'] for i in after_inputs if i['visible']]}",
            }

        # ============================================
        # ✅ PASSWORD — keyboard.type
        # ============================================
        log.info("⏳ نستنى 5s قبل password...")
        await human_delay(5, 8)
        await take_screenshot(page, f"cc_before_pwd_{attempt}")

        password_filled = False
        for sel in [
            'input[type="password"]',
            'input[name="password"]',
            'input[autocomplete="current-password"]',
        ]:
            try:
                el = page.locator(sel).first
                cnt = await el.count()
                if cnt == 0:
                    continue
                if not await el.is_visible():
                    continue

                log.info(f"✅ لقيت pwd field: {sel}")

                # ✅ نكتب بـ keyboard.type
                ok = await self._type_with_keyboard(page, el, self.password, "password")
                if ok:
                    password_filled = True
                    await human_delay(3, 5)
                    break
            except Exception as e:
                log.warning(f"فشل pwd {sel}: {e}")
                continue

        if not password_filled:
            await take_screenshot(page, f"cc_pwd_fail_{attempt}")
            return {
                "success": False,
                "reason": "ما قدرتش نكتب كلمة السر",
                "details": f"URL: {page.url[:150]}",
            }

        # ✅ Next password
        log.info("🖱️ نضغط Next (password)")
        if not await self._click_next_with_logs(page, "password"):
            return {"success": False, "reason": "ما لقيتش زر Next (password)"}

        log.info("⏳ نستنى 12s بعد Next (password)...")
        await human_delay(12, 18)
        await take_screenshot(page, f"cc_after_pwd_{attempt}")

        final_url = page.url.lower()
        if "accounts.google.com" in final_url:
            await take_screenshot(page, f"cc_still_signin_{attempt}")
            return {
                "success": False,
                "reason": "Google رجع Sign in بعد password",
                "details": f"URL: {page.url[:150]}",
            }

        log.info("✅ email + password done")
        return {"success": True}

    async def _click_next_with_logs(self, page, step: str) -> bool:
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
                cnt = await el.count()
                vis = await el.is_visible() if cnt > 0 else False
                if cnt > 0 and vis:
                    log.info(f"  ✅ كليك على {sel} ({step})")
                    await el.click()
                    return True
            except Exception:
                continue
        return False

    # ==================== Welcome ====================

    async def _handle_welcome_hard(self, page) -> bool:
        await human_delay(3, 5)

        try:
            clicked = await page.evaluate("""
                async () => {
                    const sleep = (ms) => new Promise(r => setTimeout(r, ms));
                    function findBtn() {
                        const all = document.querySelectorAll('button, a, [role="button"]');
                        for (const el of all) {
                            if (el.offsetParent === null) continue;
                            if (el.disabled) continue;
                            const t = (el.innerText || el.value || '').trim().toLowerCase();
                            if (t === 'accept' || t === 'i understand' || t === 'i agree' ||
                                t === 'agree' || t === 'continue') return el;
                        }
                        for (const el of all) {
                            if (el.offsetParent === null) continue;
                            if (el.disabled) continue;
                            const t = (el.innerText || el.value || '').trim().toLowerCase();
                            if (t.includes('accept') || t.includes('understand') ||
                                t.includes('agree')) return el;
                        }
                        return null;
                    }
                    const btn = findBtn();
                    if (!btn) return { error: 'not_found' };
                    const text = (btn.innerText || btn.value || '').trim();
                    btn.scrollIntoView({block: 'center'});
                    btn.focus();
                    await sleep(300);
                    btn.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
                    btn.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                    btn.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }));
                    btn.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                    btn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                    btn.click();
                    return { clicked: text, tag: btn.tagName };
                }
            """)
            if clicked and clicked.get("clicked"):
                log.info(f"✅ JS 5-event: {clicked}")
                return True
        except Exception as e:
            log.warning(f"JS: {e}")

        for sel in [
            'button:has-text("Accept")',
            'button:has-text("I understand")',
            'button:has-text("I agree")',
            'button[type="submit"]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() == 0:
                    continue
                if not await el.is_visible():
                    continue
                log.info(f"✅ Playwright: {sel}")
                try:
                    await el.click(timeout=3000)
                    return True
                except Exception:
                    try:
                        await el.click(force=True, timeout=3000)
                        return True
                    except Exception:
                        pass
            except Exception:
                continue
        return False

    # ==================== Helpers ====================

    async def _get_body_text(self, page, max_len: int = 400):
        try:
            text = await page.inner_text("body")
            return text[:max_len].replace('\n', ' | ')
        except Exception:
            return ""

    async def _is_welcome_page(self, page) -> bool:
        url = page.url.lower()
        if "workspacetermsofservice" in url or "speedbump" in url:
            return True
        text = (await self._get_body_text(page)).lower()
        if "welcome to your new account" in text:
            return True
        if "terms of service" in text:
            return True
        try:
            for sel in [
                'button:has-text("Accept")',
                'button:has-text("I agree")',
                'button:has-text("I understand")',
            ]:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
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
        return True

    async def _is_signin_page(self, page) -> bool:
        url = page.url.lower()
        if "accounts.google.com" in url and "workspaceterms" not in url and "speedbump" not in url:
            return True
        for sel in [
            'input[type="email"]',
            'input[type="text"][name="identifier"]',
            'input[name="identifier"]',
        ]:
            try:
                if await page.locator(sel).count() > 0:
                    return True
            except Exception:
                pass
        return False

    async def _fill_captcha(self, page, solution: str):
        for sel in [
            'input[name="ca"]',
            'input[id="ca"]',
            'input[name="captcha"]',
            'input[type="text"][aria-label*="Type the text" i]',
            'input[type="text"][aria-label*="characters" i]',
        ]:
            try:
                inp = page.locator(sel).first
                if await inp.count() == 0 or not await inp.is_visible():
                    continue
                await inp.click()
                await human_delay(0.3, 0.6)
                await inp.fill("")
                await human_delay(0.2, 0.4)
                await inp.fill(solution)
                await human_delay(0.5, 1.0)

                val = await inp.input_value()
                if val.strip():
                    log.info(f"✍️ كتبت: {val}")
                    for btn_sel in [
                        '#captchaNext',
                        'button:has-text("Next")',
                        'input[type="submit"]',
                        'button[type="submit"]',
                        '#identifierNext',
                    ]:
                        try:
                            btn = page.locator(btn_sel).first
                            if await btn.count() > 0 and await btn.is_visible():
                                await btn.click()
                                await human_delay(5, 8)
                                return True
                        except Exception:
                            continue
                    return True
            except Exception as e:
                log.warning(f"فشل {sel}: {e}")
                continue
        return False

    async def _do_signin(self, page, username: str, password: str):
        return await self._do_signin_with_analysis(page, 0)

    async def _click_next(self, page, step: str):
        return await self._click_next_with_logs(page, step)
