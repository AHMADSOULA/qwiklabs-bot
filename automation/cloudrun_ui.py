import asyncio
from utils.logger import get_logger
from utils.helpers import human_delay
from utils.screenshot import take_screenshot

log = get_logger("CloudRunUI")


class CloudRunUI:
    """ينشر على Cloud Run عبر واجهة المستخدم (UI)"""

    def __init__(self, context):
        self.context = context
        self.sender = None

    async def deploy(self, page, service_name: str, image: str,
                     region: str = "us-central1", memory: str = "2Gi",
                     cpu: str = "2", port: int = 8080,
                     sender=None) -> str:
        self.sender = sender

        log.info(f"🚀 نشر {service_name} على {region} (UI)")

        # ✅ 1. نروحو مباشرة لـ Create Service page
        url = "https://console.cloud.google.com/run/create"
        log.info(f"🌐 فتح: {url}")
        await page.goto(url, wait_until="domcontentloaded")
        await human_delay(8, 12)
        await self._send_shot(page, "📸 صفحة Create Service")

        log.info(f"URL الحالي: {page.url[:150]}")

        # ✅ 2. نتأكدو واش الصفحة تحملت
        await self._wait_for_page_load(page)

        # ✅ 3. نختارو Container Image URL
        log.info("🐳 نختار Container Image URL...")
        await self._select_container_image(page)
        await human_delay(2, 3)
        await self._send_shot(page, "📸 بعد Container Image")

        # ✅ 4. نعبّيو Image URL
        log.info(f"🐳 Image: {image}")
        await self._fill_image(page, image)
        await human_delay(3, 5)
        await self._send_shot(page, "📸 بعد Image")

        # ✅ 5. نختارو Region
        log.info(f"🌍 Region: {region}")
        await self._select_region(page, region)
        await human_delay(2, 3)

        # ✅ 6. نضبطو RAM + CPU
        log.info(f"💾 RAM: {memory} | ⚙️ CPU: {cpu}")
        await self._set_resources(page, memory, cpu)
        await human_delay(2, 3)

        # ✅ 7. نضبطو Port
        log.info(f"🔌 Port: {port}")
        await self._set_port(page, port)
        await human_delay(2, 3)

        # ✅ 8. نضبطو Service name
        log.info(f"📦 Service: {service_name}")
        await self._set_service_name(page, service_name)
        await human_delay(2, 3)

        # ✅ 9. نضبطو Authentication = Allow unauthenticated
        log.info("🔓 Allow unauthenticated...")
        await self._set_auth_unauthenticated(page)
        await human_delay(2, 3)

        # ✅ 10. نضغطو Create
        log.info("🖱️ نضغط Create...")
        created = await self._click_final_create(page)
        if not created:
            await self._send_shot(page, "❌ ما لقيناش Create")
            raise RuntimeError("ما لقيناش زر Create النهائي")

        await human_delay(5, 8)
        await self._send_shot(page, "📸 بعد Create")

        # ✅ 11. ننتظرو النشر
        log.info("⏳ ننتظر النشر...")
        service_url = await self._wait_for_deployment(page, timeout=300)
        if service_url:
            log.info(f"✅ {service_url}")
            return service_url

        raise RuntimeError("ما لقيناش URL النهائي")

    # ==================== Wait for Page Load ====================

    async def _wait_for_page_load(self, page, timeout: int = 60):
        log.info("⏳ ننتظر الصفحة تحمل...")
        for i in range(timeout // 3):
            await asyncio.sleep(3)
            try:
                info = await page.evaluate("""
                    () => {
                        const inputs = document.querySelectorAll('input');
                        const buttons = document.querySelectorAll('button');
                        const text = (document.body.innerText || '').toLowerCase();
                        return {
                            inputs: inputs.length,
                            buttons: buttons.length,
                            has_image_field: text.includes('container image') || text.includes('image url'),
                            has_create: text.includes('create'),
                            url: window.location.href.substring(0, 200),
                        };
                    }
                """)
                log.info(f"📋 inputs: {info.get('inputs')}, buttons: {info.get('buttons')}, has_image_field: {info.get('has_image_field')}")

                if info.get('inputs', 0) > 3 and info.get('buttons', 0) > 3:
                    log.info("✅ الصفحة تحملت")
                    return True
            except Exception:
                pass
        return False

    # ==================== Select Container Image ====================

    async def _select_container_image(self, page):
        """يختار Container Image URL"""
        for sel in [
            'button:has-text("Container Image URL")',
            'label:has-text("Container Image URL")',
            '[role="radio"]:has-text("Container Image URL")',
            'button:has-text("Container image")',
            'label:has-text("Container image")',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    log.info(f"✅ Container Image: {sel}")
                    await el.click()
                    await human_delay(1, 2)
                    return
            except Exception:
                continue

        # ✅ JS
        try:
            clicked = await page.evaluate("""
                () => {
                    for (const el of document.querySelectorAll('label, button, [role="radio"], [role="button"]')) {
                        if (el.offsetParent === null) continue;
                        const t = (el.innerText || '').trim().toLowerCase();
                        if (t.includes('container image') || t.includes('container image url')) {
                            el.click();
                            return t;
                        }
                    }
                    return null;
                }
            """)
            if clicked:
                log.info(f"✅ JS Container Image: {clicked}")
                await human_delay(1, 2)
        except Exception:
            pass

    # ==================== Fill Image ====================

    async def _fill_image(self, page, image: str):
        """يعبّي Image URL"""
        for sel in [
            'input[aria-label*="Container image URL" i]',
            'input[aria-label*="Image URL" i]',
            'input[aria-label*="image" i]',
            'input[placeholder*="image" i]',
            'input[placeholder*="us-docker" i]',
            'input[name*="image" i]',
            'input[formcontrolname*="image" i]',
            'input[type="text"]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() == 0 or not await el.is_visible():
                    continue
                log.info(f"✅ Image field: {sel}")
                await el.scroll_into_view_if_needed()
                await el.click()
                await human_delay(0.5, 1)
                await el.fill("")
                await human_delay(0.3, 0.5)
                await el.fill(image)
                await human_delay(1, 2)
                return
            except Exception:
                continue

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
                # ✅ نمسحو القيمة الحالية
                await el.fill("")
                await human_delay(0.3, 0.5)
                await page.keyboard.type(region, delay=80)
                await human_delay(1, 2)
                await page.keyboard.press("Enter")
                await human_delay(1, 2)
                log.info(f"✅ Region: {region}")
                return
            except Exception:
                continue

    # ==================== Set Resources ====================

    async def _set_resources(self, page, memory: str, cpu: str):
        # ✅ نضغطو "Container, Networking, Security" tab
        for sel in [
            'button:has-text("Container, Networking, Security")',
            'button:has-text("Container(s)")',
            'button:has-text("Container")',
            '[role="tab"]:has-text("Container")',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.click()
                    await human_delay(2, 3)
                    break
            except Exception:
                continue

        # ✅ RAM
        for sel in [
            'input[aria-label*="Memory" i]',
            '[role="combobox"][aria-label*="Memory" i]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.click()
                    await human_delay(1, 2)
                    await el.fill("")
                    await human_delay(0.3, 0.5)
                    await page.keyboard.type(memory, delay=80)
                    await human_delay(1, 2)
                    await page.keyboard.press("Enter")
                    await human_delay(1, 2)
                    log.info(f"✅ RAM: {memory}")
                    break
            except Exception:
                continue

        # ✅ CPU
        for sel in [
            'input[aria-label*="CPU" i]',
            '[role="combobox"][aria-label*="CPU" i]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.click()
                    await human_delay(1, 2)
                    await el.fill("")
                    await human_delay(0.3, 0.5)
                    await page.keyboard.type(cpu, delay=80)
                    await human_delay(1, 2)
                    await page.keyboard.press("Enter")
                    await human_delay(1, 2)
                    log.info(f"✅ CPU: {cpu}")
                    break
            except Exception:
                continue

    # ==================== Set Port ====================

    async def _set_port(self, page, port: int):
        for sel in [
            'input[aria-label*="Container port" i]',
            'input[aria-label*="Port" i]',
            'input[name*="port" i]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.click()
                    await human_delay(0.5, 1)
                    await el.fill("")
                    await el.fill(str(port))
                    log.info(f"✅ Port: {port}")
                    return
            except Exception:
                continue

    # ==================== Set Service Name ====================

    async def _set_service_name(self, page, service_name: str):
        for sel in [
            'input[aria-label*="Service name" i]',
            'input[aria-label*="name" i]',
            'input[formcontrolname*="serviceName" i]',
            'input[formcontrolname*="name" i]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() == 0 or not await el.is_visible():
                    continue
                # ✅ نتحققو إذا الحقل ماشي فارغ
                current = await el.input_value()
                if current and current.strip():
                    log.info(f"✅ Service name موجود: {current}")
                    return
                await el.click()
                await human_delay(0.5, 1)
                await el.fill("")
                await human_delay(0.3, 0.5)
                await el.fill(service_name)
                await human_delay(1, 2)
                log.info(f"✅ Service name: {service_name}")
                return
            except Exception:
                continue

    # ==================== Set Auth ====================

    async def _set_auth_unauthenticated(self, page):
        """Allow unauthenticated"""
        try:
            # ✅ نلقاو radio "Allow unauthenticated invocations"
            clicked = await page.evaluate("""
                () => {
                    for (const el of document.querySelectorAll('label, [role="radio"], input[type="radio"]')) {
                        if (el.offsetParent === null) continue;
                        const t = (el.innerText || el.value || '').toLowerCase();
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
                await human_delay(1, 2)
        except Exception as e:
            log.warning(f"auth: {e}")

    # ==================== Click Final Create ====================

    async def _click_final_create(self, page) -> bool:
        log.info("🔍 نبحث عن زر Create...")

        # ✅ نسجل الأزرار
        try:
            buttons = await page.evaluate("""
                () => {
                    const r = [];
                    for (const el of document.querySelectorAll('button, input[type="submit"], [role="button"]')) {
                        if (el.offsetParent === null) continue;
                        const t = (el.innerText || el.value || '').trim();
                        if (t && t.length < 60) r.push(t);
                    }
                    return r;
                }
            """)
            log.info(f"📋 الأزرار: {buttons}")
        except Exception:
            pass

        # ✅ 1. Playwright locators
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

        # ✅ 2. JS
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
                                el.scroll_into_view_if_needed();
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

        # ✅ 3. آخر زر أزرق
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
