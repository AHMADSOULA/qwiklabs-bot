import asyncio
from utils.logger import get_logger
from utils.helpers import human_delay
from utils.screenshot import take_screenshot

log = get_logger("CloudRunUI")


class CloudRunUI:
    """ينشر على Cloud Run عبر UI — خطوات 4→5→6 من الشرح"""

    def __init__(self, context):
        self.context = context
        self.sender = None

    async def deploy(self, page, service_name: str, image: str,
                     region: str = "europe-west1", memory: str = "2Gi",
                     cpu: str = "2", port: int = 8080,
                     sender=None) -> str:
        self.sender = sender

        log.info(f"🚀 نشر {service_name} على {region}")

        # ✅ الخطوة 4: نروحو للـ Dashboard
        log.info("🌐 [الخطوة 4] Dashboard...")
        await msg_edit_safe(sender, "📸 الخطوة 4: Dashboard")
        await self._goto_dashboard(page)
        await human_delay(5, 8)
        await self._send_shot(page, "📸 Dashboard")

        # ✅ الخطوة 4.2: نضغطو على Cloud Run فـ القائمة
        log.info("🖱️ [الخطوة 4] نضغط Cloud Run...")
        await self._click_cloud_run_link(page)
        await human_delay(5, 8)
        await self._send_shot(page, "📸 Cloud Run")

        # ✅ الخطوة 5: نضغطو على "Deploy container"
        log.info("🖱️ [الخطوة 5] Deploy container...")
        await self._click_deploy_container(page)
        await human_delay(8, 12)
        await self._send_shot(page, "📸 Create Service")

        # ✅ الخطوة 6: نعبّيو الحقول
        log.info("📝 [الخطوة 6] تعبئة الحقول...")

        # 6.1 Image URL
        log.info(f"🐳 Image: {image}")
        await self._fill_image(page, image)
        await human_delay(2, 3)
        await self._send_shot(page, "📸 بعد Image")

        # 6.2 Service name
        log.info(f"📦 Service: {service_name}")
        await self._fill_service_name(page, service_name)
        await human_delay(2, 3)

        # 6.3 Region
        log.info(f"🌍 Region: {region}")
        await self._select_region(page, region)
        await human_delay(2, 3)

        # 6.4 Authentication: Allow public access
        log.info("🔓 Allow public access")
        await self._set_public_access(page)
        await human_delay(1, 2)

        # 6.5 Ingress: All
        log.info("🌐 Ingress: All")
        await self._set_ingress_all(page)
        await human_delay(1, 2)

        # 6.6 Container(s) — RAM + CPU + Port
        log.info(f"💾 RAM: {memory} | ⚙️ CPU: {cpu} | 🔌 Port: {port}")
        await self._set_container_resources(page, memory, cpu, port)
        await human_delay(2, 3)

        await self._send_shot(page, "📸 بعد تعبئة الحقول")

        # ✅ 7: نضغطو Create
        log.info("🖱️ نضغط Create...")
        created = await self._click_create(page)
        if not created:
            raise RuntimeError("ما لقيناش زر Create")

        await human_delay(5, 8)
        await self._send_shot(page, "📸 بعد Create")

        # ✅ 8: ننتظرو النشر
        log.info("⏳ ننتظر النشر...")
        service_url = await self._wait_for_deployment(page, timeout=300)
        if service_url:
            log.info(f"✅ {service_url}")
            return service_url

        raise RuntimeError("ما لقيناش URL النهائي")

    # ==================== Step 4: Dashboard ====================

    async def _goto_dashboard(self, page):
        """يروح للـ Dashboard"""
        try:
            await page.goto(
                "https://console.cloud.google.com/home/dashboard",
                wait_until="domcontentloaded",
                timeout=60000
            )
        except Exception as e:
            log.warning(f"Dashboard goto: {e}")
        await human_delay(5, 8)

    async def _click_cloud_run_link(self, page):
        """يضغط على Cloud Run فـ القائمة"""
        # ✅ نبحث فـ القائمة
        for sel in [
            'a:has-text("Cloud Run")',
            'button:has-text("Cloud Run")',
            '[role="link"]:has-text("Cloud Run")',
            '[role="button"]:has-text("Cloud Run")',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    log.info(f"✅ Cloud Run link: {sel}")
                    await el.scroll_into_view_if_needed()
                    await el.click(timeout=5000)
                    await human_delay(5, 8)
                    return True
            except Exception:
                continue

        # ✅ JS
        try:
            clicked = await page.evaluate("""
                () => {
                    const kws = ['cloud run'];
                    for (const el of document.querySelectorAll('a, button, [role="link"], [role="button"]')) {
                        if (el.offsetParent === null) continue;
                        const t = (el.innerText || '').trim().toLowerCase();
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
                log.info(f"✅ JS Cloud Run: {clicked}")
                await human_delay(5, 8)
                return True
        except Exception:
            pass

        # ✅ نروحو مباشرة
        log.warning("⚠️ ما لقيناش Cloud Run link — نروحو مباشرة")
        try:
            await page.goto(
                "https://console.cloud.google.com/run",
                wait_until="domcontentloaded",
                timeout=60000
            )
        except Exception:
            pass
        await human_delay(5, 8)
        return False

    # ==================== Step 5: Deploy container ====================

    async def _click_deploy_container(self, page):
        """يضغط على Deploy container"""
        for sel in [
            'button:has-text("Deploy container")',
            'a:has-text("Deploy container")',
            '[role="button"]:has-text("Deploy container")',
            'button:has-text("Create Service")',
            'a:has-text("Create Service")',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    log.info(f"✅ {sel}")
                    await el.scroll_into_view_if_needed()
                    await el.click(timeout=5000)
                    await human_delay(8, 12)
                    return True
            except Exception:
                continue

        # ✅ JS
        try:
            clicked = await page.evaluate("""
                () => {
                    const kws = ['deploy container', 'create service'];
                    for (const el of document.querySelectorAll('button, a, [role="button"]')) {
                        if (el.offsetParent === null) continue;
                        const t = (el.innerText || '').trim().toLowerCase();
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
                await human_delay(8, 12)
                return True
        except Exception:
            pass

        return False

    # ==================== Step 6: Fill fields ====================

    async def _fill_image(self, page, image: str):
        """يعبّي Container image URL"""
        for sel in [
            'input[aria-label*="Container image URL" i]',
            'input[aria-label*="Image URL" i]',
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
                return True
            except Exception:
                continue
        return False

    async def _fill_service_name(self, page, service_name: str):
        """يعبّي Service name"""
        for sel in [
            'input[aria-label*="Service name" i]',
            'input[aria-label*="Name" i]',
            'input[formcontrolname*="serviceName" i]',
            'input[formcontrolname*="name" i]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() == 0 or not await el.is_visible():
                    continue
                current = await el.input_value()
                if current and current.strip():
                    log.info(f"✅ Service name موجود: {current}")
                    return True
                await el.click()
                await human_delay(0.5, 1)
                await el.fill("")
                await human_delay(0.3, 0.5)
                await el.fill(service_name)
                await human_delay(1, 2)
                log.info(f"✅ Service name: {service_name}")
                return True
            except Exception:
                continue
        return False

    async def _select_region(self, page, region: str):
        """يختار Region"""
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
                log.info(f"✅ Region: {region}")
                return True
            except Exception:
                continue
        return False

    async def _set_public_access(self, page):
        """Authentication: Allow public access"""
        try:
            clicked = await page.evaluate("""
                () => {
                    for (const el of document.querySelectorAll('label, [role="radio"], input[type="radio"]')) {
                        if (el.offsetParent === null) continue;
                        const t = (el.innerText || el.value || el.getAttribute('aria-label') || '').toLowerCase();
                        if (t.includes('allow public') || t.includes('allow unauthenticated')) {
                            el.click();
                            return t;
                        }
                    }
                    return null;
                }
            """)
            if clicked:
                log.info(f"✅ Public access: {clicked}")
                return True
        except Exception:
            pass
        return False

    async def _set_ingress_all(self, page):
        """Ingress: All"""
        try:
            clicked = await page.evaluate("""
                () => {
                    for (const el of document.querySelectorAll('label, [role="radio"], input[type="radio"]')) {
                        if (el.offsetParent === null) continue;
                        const t = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().toLowerCase();
                        if (t === 'all' || t.includes('allow direct access')) {
                            el.click();
                            return t;
                        }
                    }
                    return null;
                }
            """)
            if clicked:
                log.info(f"✅ Ingress: {clicked}")
                return True
        except Exception:
            pass
        return False

    async def _set_container_resources(self, page, memory: str, cpu: str, port: int):
        """RAM + CPU + Port"""
        # نضغطو على "Container(s), Networking, Security"
        for sel in [
            'button:has-text("Container")',
            'button:has-text("Container(s)")',
            'button:has-text("Container(s), Networking, Security")',
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

        # RAM
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
                    break
            except Exception:
                continue

        # CPU
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
                    break
            except Exception:
                continue

        # Port
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
                    break
            except Exception:
                continue

    # ==================== Create ====================

    async def _click_create(self, page):
        """يضغط Create"""
        # نسجل الأزرار
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

        # ✅ Playwright
        for sel in [
            'button:has-text("Create")',
            'button:has-text("Deploy")',
            '[role="button"]:has-text("Create")',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    txt = (await el.inner_text()).strip().lower()
                    if 'cancel' in txt:
                        continue
                    log.info(f"✅ Create: {sel}")
                    await el.click(timeout=5000)
                    return True
            except Exception:
                continue

        # ✅ JS
        try:
            clicked = await page.evaluate("""
                () => {
                    for (const el of document.querySelectorAll('button, input[type="submit"], [role="button"]')) {
                        if (el.offsetParent === null || el.disabled) continue;
                        const t = (el.innerText || el.value || '').trim().toLowerCase();
                        if (!t || t.length > 100) continue;
                        if (t.includes('cancel') || t.includes('delete')) continue;
                        if (t === 'create' || t.includes('create') || t.includes('deploy')) {
                            el.scrollIntoView({block: 'center'});
                            el.click();
                            return t;
                        }
                    }
                    return null;
                }
            """)
            if clicked:
                log.info(f"✅ JS Create: {clicked}")
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


async def msg_edit_safe(sender, text: str):
    try:
        if sender:
            await sender.reply_text(text)
    except Exception:
        pass
