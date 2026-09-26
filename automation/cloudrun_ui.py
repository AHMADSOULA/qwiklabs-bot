import asyncio
from utils.logger import get_logger
from utils.helpers import human_delay
from utils.screenshot import take_screenshot

log = get_logger("CloudRunUI")


class CloudRunUI:
    """ينشر على Cloud Run عبر UI"""

    def __init__(self, context):
        self.context = context
        self.sender = None

    async def deploy(self, page, service_name: str, image: str,
                     region: str = "us-central1", memory: str = "2Gi",
                     cpu: str = "2", port: int = 8080,
                     sender=None) -> str:
        self.sender = sender

        log.info(f"🚀 نشر {service_name} على {region}")

        # ✅ 1. نستنو 5 ثواني بعد تسجيل الدخول + Screenshot
        log.info("⏳ ننتظر 5 ثواني بعد تسجيل الدخول...")
        await human_delay(5, 8)
        await self._send_shot(page, "📸 بعد تسجيل الدخول")

        # ✅ 2. نروحو لـ Cloud Run مباشرة
        url = "https://console.cloud.google.com/run/create"
        log.info(f"🌐 فتح: {url}")
        await page.goto(url, wait_until="domcontentloaded")
        await human_delay(8, 12)
        await self._send_shot(page, "📸 صفحة Create Service")
        log.info(f"URL: {page.url[:150]}")

        # ✅ 3. نتحققو واش الصفحة تحملت + نسجلو الحقول
        page_info = await self._inspect_page(page)
        log.info(f"📋 Inputs: {page_info.get('inputs', [])}")
        log.info(f"📋 Buttons: {page_info.get('buttons', [])}")
        log.info(f"📋 Radios: {page_info.get('radios', [])}")

        # ✅ 4. نعبّيو الحقول بالترتيب
        # 4.1 Service name
        log.info(f"📦 Service: {service_name}")
        await self._fill_field(page, ["Service name", "Name"], service_name)
        await human_delay(1, 2)

        # 4.2 Region
        log.info(f"🌍 Region: {region}")
        await self._select_region(page, region)
        await human_delay(1, 2)

        # 4.3 Container Image URL
        log.info(f"🐳 Image: {image}")
        await self._fill_field(page, [
            "Container image URL",
            "Container image",
            "Image URL",
            "Image",
        ], image)
        await human_delay(2, 3)
        await self._send_shot(page, "📸 بعد Image")

        # 4.4 Container port
        log.info(f"🔌 Port: {port}")
        await self._fill_field(page, ["Container port", "Port"], str(port))
        await human_delay(1, 2)

        # 4.5 RAM + CPU
        log.info(f"💾 RAM: {memory} | ⚙️ CPU: {cpu}")
        await self._fill_field(page, ["Memory", "Memory limit"], memory)
        await human_delay(1, 2)
        await self._fill_field(page, ["CPU", "CPU limit"], cpu)
        await human_delay(1, 2)

        # 4.6 Allow unauthenticated
        log.info("🔓 Allow unauthenticated...")
        await self._allow_unauthenticated(page)
        await human_delay(1, 2)

        await self._send_shot(page, "📸 بعد تعبئة الحقول")

        # ✅ 5. نضغطو Create
        log.info("🖱️ نضغط Create...")
        created = await self._click_create(page)
        if not created:
            await self._send_shot(page, "❌ ما لقيناش Create")
            # ✅ نسجلو الأزرار باش نعرفو
            info = await self._inspect_page(page)
            log.error(f"❌ الأزرار: {info.get('buttons', [])}")
            raise RuntimeError(f"ما لقيناش زر Create — الأزرار: {info.get('buttons', [])[:10]}")

        await human_delay(5, 8)
        await self._send_shot(page, "📸 بعد Create")

        # ✅ 6. ننتظرو النشر
        log.info("⏳ ننتظر النشر...")
        service_url = await self._wait_for_deployment(page, timeout=300)
        if service_url:
            log.info(f"✅ {service_url}")
            return service_url

        raise RuntimeError("ما لقيناش URL النهائي")

    # ==================== Inspect Page ====================

    async def _inspect_page(self, page) -> dict:
        """يسجل كل الحقول والأزرار"""
        try:
            return await page.evaluate("""
                () => {
                    const r = {
                        inputs: [],
                        buttons: [],
                        radios: [],
                        url: window.location.href.substring(0, 200),
                    };
                    for (const inp of document.querySelectorAll('input')) {
                        if (inp.offsetParent === null) continue;
                        r.inputs.push({
                            type: inp.type || '',
                            name: inp.name || '',
                            id: inp.id || '',
                            aria: inp.getAttribute('aria-label') || '',
                            placeholder: inp.placeholder || '',
                            value: (inp.value || '').substring(0, 30),
                            formcontrol: inp.getAttribute('formcontrolname') || '',
                        });
                    }
                    for (const btn of document.querySelectorAll('button, input[type="submit"], [role="button"]')) {
                        if (btn.offsetParent === null) continue;
                        const t = (btn.innerText || btn.value || '').trim();
                        if (t && t.length < 60) r.buttons.push(t);
                    }
                    for (const rd of document.querySelectorAll('[role="radio"], input[type="radio"]')) {
                        if (rd.offsetParent === null) continue;
                        const t = (rd.innerText || rd.value || rd.getAttribute('aria-label') || '').trim();
                        if (t) r.radios.push(t.substring(0, 60));
                    }
                    return r;
                }
            """)
        except Exception as e:
            return {"error": str(e)}

    # ==================== Fill Field ====================

    async def _fill_field(self, page, labels: list, value: str) -> bool:
        """يعبّي حقل بأي label من القائمة"""
        for label in labels:
            # ✅ طرق متعددة للبحث
            selectors = [
                f'input[aria-label*="{label}" i]',
                f'input[placeholder*="{label}" i]',
                f'input[formcontrolname*="{label.lower().replace(" ", "")}" i]',
                f'input[name*="{label.lower().replace(" ", "")}" i]',
            ]
            for sel in selectors:
                try:
                    el = page.locator(sel).first
                    if await el.count() == 0 or not await el.is_visible():
                        continue
                    log.info(f"✅ {label}: {sel}")
                    await el.scroll_into_view_if_needed()
                    await el.click()
                    await human_delay(0.3, 0.5)
                    await el.fill("")
                    await human_delay(0.2, 0.4)
                    await el.fill(value)
                    await human_delay(0.5, 1)
                    # ✅ نتحققو
                    v = await el.input_value()
                    if v.strip():
                        log.info(f"✅ {label} = {v}")
                        return True
                except Exception:
                    continue

            # ✅ JS
            try:
                filled = await page.evaluate(f"""
                    (args) => {{
                        const labels = args.labels;
                        const value = args.value;
                        for (const inp of document.querySelectorAll('input')) {{
                            if (inp.offsetParent === null) continue;
                            const aria = (inp.getAttribute('aria-label') || '').toLowerCase();
                            const ph = (inp.placeholder || '').toLowerCase();
                            const name = (inp.name || '').toLowerCase();
                            for (const lb of labels) {{
                                const l = lb.toLowerCase();
                                if (aria.includes(l) || ph.includes(l) || name.includes(l)) {{
                                    inp.focus();
                                    inp.value = value;
                                    inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                    inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                    inp.dispatchEvent(new KeyboardEvent('keyup', {{ bubbles: true }}));
                                    return true;
                                }}
                            }}
                        }}
                        return false;
                    }}
                """, {"labels": labels, "value": value})
                if filled:
                    log.info(f"✅ {label} (JS) = {value}")
                    return True
            except Exception:
                pass

        log.warning(f"⚠️ ما لقيناش حقل: {labels}")
        return False

    # ==================== Select Region ====================

    async def _select_region(self, page, region: str):
        for sel in [
            'input[aria-label*="Region" i]',
            '[role="combobox"][aria-label*="Region" i]',
            'input[formcontrolname*="region" i]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() == 0 or not await el.is_visible():
                    continue
                await el.click()
                await human_delay(1, 2)
                await el.fill("")
                await human_delay(0.3, 0.5)
                await page.keyboard.type(region, delay=80)
                await human_delay(1, 2)
                await page.keyboard.press("Enter")
                await human_delay(1, 2)
                log.info(f"✅ Region = {region}")
                return
            except Exception:
                continue

    # ==================== Allow Unauthenticated ====================

    async def _allow_unauthenticated(self, page):
        try:
            clicked = await page.evaluate("""
                () => {
                    for (const el of document.querySelectorAll('label, [role="radio"], input[type="radio"]')) {
                        if (el.offsetParent === null) continue;
                        const t = (el.innerText || el.value || el.getAttribute('aria-label') || '').toLowerCase();
                        if (t.includes('allow unauthenticated') || t.includes('allow all')) {
                            el.click();
                            return t;
                        }
                    }
                    return null;
                }
            """)
            if clicked:
                log.info(f"✅ Auth: {clicked}")
        except Exception:
            pass

    # ==================== Click Create ====================

    async def _click_create(self, page) -> bool:
        log.info("🔍 نبحث عن زر Create...")

        # ✅ نسجل الأزرار
        info = await self._inspect_page(page)
        log.info(f"📋 الأزرار: {info.get('buttons', [])}")

        # ✅ نضغطو على Create
        for sel in [
            'button:has-text("Create")',
            'button:has-text("Deploy")',
            '[role="button"]:has-text("Create")',
            '[role="button"]:has-text("Deploy")',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    txt = (await el.inner_text()).strip().lower()
                    if 'cancel' in txt:
                        continue
                    log.info(f"✅ Create: {sel}")
                    await el.click(timeout=5000)
                    await human_delay(5, 8)
                    return True
            except Exception:
                continue

        # ✅ JS
        try:
            clicked = await page.evaluate("""
                () => {
                    const kws = ['create', 'deploy'];
                    for (const el of document.querySelectorAll('button, input[type="submit"], [role="button"]')) {
                        if (el.offsetParent === null || el.disabled) continue;
                        const t = (el.innerText || el.value || '').trim().toLowerCase();
                        if (!t || t.length > 100) continue;
                        if (t.includes('cancel') || t.includes('delete')) continue;
                        for (const kw of kws) {
                            if (t === kw || t.includes(kw)) {
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
                await human_delay(5, 8)
                return True
        except Exception:
            pass

        # ✅ زر أزرق
        try:
            clicked = await page.evaluate("""
                () => {
                    for (const el of document.querySelectorAll('button, input[type="submit"]')) {
                        if (el.offsetParent === null || el.disabled) continue;
                        const bg = window.getComputedStyle(el).backgroundColor;
                        if (bg.includes('11, 87') || bg.includes('26, 115') || bg.includes('66, 133')) {
                            const t = (el.innerText || '').trim().toLowerCase();
                            if (t.includes('cancel')) continue;
                            el.click();
                            return t || 'blue-button';
                        }
                    }
                    return null;
                }
            """)
            if clicked:
                log.info(f"✅ Blue: {clicked}")
                await human_delay(5, 8)
                return True
        except Exception:
            pass

        return False

    # ==================== Wait for Deployment ====================

    async def _wait_for_deployment(self, page, timeout: int = 300) -> str:
        log.info(f"⏳ ننتظر {timeout}s...")
        for i in range(timeout // 5):
            await asyncio.sleep(5)
            try:
                url = await page.evaluate("""
                    () => {
                        const links = document.querySelectorAll('a[href*=".run.app"]');
                        for (const a of links) {
                            if (a.href && a.href.includes('.run.app')) return a.href;
                        }
                        const body = document.body.innerText || '';
                        const m = body.match(/https:\\/\\/[a-zA-Z0-9\\-]+\\.run\\.app/);
                        if (m) return m[0];
                        return null;
                    }
                """)
                if url:
                    log.info(f"✅ URL: {url}")
                    return url
            except Exception:
                pass
        return None

    # ==================== Screenshot ====================

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
