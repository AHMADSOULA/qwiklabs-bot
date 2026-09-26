import asyncio
from utils.logger import get_logger
from utils.helpers import human_delay
from utils.screenshot import take_screenshot

log = get_logger("CloudRunUI")


class CloudRunUI:
    """ينشر على Cloud Run عبر واجهة المستخدم (UI) — بلا API"""

    def __init__(self, context):
        self.context = context
        self.sender = None

    async def deploy(self, page, service_name: str, image: str,
                     region: str = "us-central1", memory: str = "2Gi",
                     cpu: str = "2", port: int = 8080,
                     sender=None) -> str:
        self.sender = sender

        log.info(f"🚀 نشر {service_name} على {region} (UI)")

        # ✅ 1. نروحو لـ Cloud Run
        url = "https://console.cloud.google.com/run"
        log.info(f"🌐 فتح: {url}")
        await page.goto(url, wait_until="domcontentloaded")
        await human_delay(5, 8)
        await self._send_shot(page, "📸 صفحة Cloud Run")

        # ✅ 2. نضغطو على "Create Service" ولا "Deploy Container"
        log.info("🔍 نبحث عن زر Create...")
        clicked = await self._click_create(page)
        if not clicked:
            raise RuntimeError("ما لقيناش زر Create")

        await human_delay(5, 8)
        await self._send_shot(page, "📸 بعد Create")

        # ✅ 3. نختارو Container Image
        log.info("🐳 نختار Container Image...")
        await self._select_container_image(page)
        await human_delay(2, 3)

        # ✅ 4. نعبّيو Image URL
        log.info(f"🐳 Image: {image}")
        await self._fill_image(page, image)
        await human_delay(2, 3)
        await self._send_shot(page, "📸 بعد Image")

        # ✅ 5. نختارو Region
        log.info(f"🌍 Region: {region}")
        await self._select_region(page, region)
        await human_delay(2, 3)

        # ✅ 6. نختارو RAM + CPU
        log.info(f"💾 RAM: {memory} | ⚙️ CPU: {cpu}")
        await self._set_resources(page, memory, cpu)
        await human_delay(2, 3)

        # ✅ 7. نضبطو Port
        if port != 8080:
            log.info(f"🔌 Port: {port}")
            await self._set_port(page, port)
            await human_delay(2, 3)

        # ✅ 8. نضغطو Create
        log.info("🖱️ نضغط Create...")
        created = await self._click_final_create(page)
        if not created:
            raise RuntimeError("ما لقيناش زر Create النهائي")

        await human_delay(5, 8)
        await self._send_shot(page, "📸 بعد Create النهائي")

        # ✅ 9. ننتظرو النشر يكمل
        log.info("⏳ ننتظر النشر...")
        service_url = await self._wait_for_deployment(page, timeout=300)
        if service_url:
            log.info(f"✅ {service_url}")
            return service_url

        raise RuntimeError("ما لقيناش URL النهائي")

    # ==================== Click Create ====================

    async def _click_create(self, page) -> bool:
        """يضغط على زر Create"""
        # ✅ نبحث عن "Create Service" ولا "Deploy Container"
        for sel in [
            'button:has-text("Create Service")',
            'button:has-text("Deploy Container")',
            'a:has-text("Create Service")',
            'a:has-text("Deploy Container")',
            '[role="button"]:has-text("Create")',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    log.info(f"✅ لقينا: {sel}")
                    await el.click(timeout=5000)
                    return True
            except Exception:
                continue

        # ✅ JS
        try:
            clicked = await page.evaluate("""
                () => {
                    const kws = ['create service', 'deploy container', 'create'];
                    for (const el of document.querySelectorAll('button, a, [role="button"]')) {
                        if (el.offsetParent === null) continue;
                        const t = (el.innerText || '').trim().toLowerCase();
                        if (!t) continue;
                        for (const kw of kws) {
                            if (t === kw || t.includes(kw)) {
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
                return True
        except Exception:
            pass

        return False

    # ==================== Select Container Image ====================

    async def _select_container_image(self, page):
        """يختار Container Image"""
        for sel in [
            'button:has-text("Container Image")',
            'label:has-text("Container Image")',
            '[role="radio"]:has-text("Container Image")',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    log.info(f"✅ Container Image: {sel}")
                    await el.click()
                    return
            except Exception:
                continue

    # ==================== Fill Image ====================

    async def _fill_image(self, page, image: str):
        """يعبّي Image URL"""
        for sel in [
            'input[aria-label*="Container image URL" i]',
            'input[aria-label*="Image URL" i]',
            'input[placeholder*="image" i]',
            'input[name*="image" i]',
            'input[formcontrolname*="image" i]',
            'input[type="text"]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() == 0 or not await el.is_visible():
                    continue
                log.info(f"✅ Image field: {sel}")
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
        """يختار Region"""
        for sel in [
            'input[aria-label*="Region" i]',
            '[role="combobox"][aria-label*="Region" i]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() == 0 or not await el.is_visible():
                    continue
                await el.click()
                await human_delay(1, 2)
                # ✅ نكتبو اسم المنطقة
                await page.keyboard.type(region, delay=80)
                await human_delay(1, 2)
                # ✅ نضغطو Enter
                await page.keyboard.press("Enter")
                await human_delay(1, 2)
                return
            except Exception:
                continue

    # ==================== Set Resources ====================

    async def _set_resources(self, page, memory: str, cpu: str):
        """يضبط RAM + CPU"""
        # ✅ نضغطو "Container, Networking, Security" ولا "Container(s)"
        for sel in [
            'button:has-text("Container")',
            'button:has-text("Container(s)")',
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
                    await page.keyboard.type(memory, delay=80)
                    await human_delay(1, 2)
                    await page.keyboard.press("Enter")
                    await human_delay(1, 2)
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
                    await page.keyboard.type(cpu, delay=80)
                    await human_delay(1, 2)
                    await page.keyboard.press("Enter")
                    await human_delay(1, 2)
                    break
            except Exception:
                continue

    # ==================== Set Port ====================

    async def _set_port(self, page, port: int):
        """يضبط Port"""
        for sel in [
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
                    return
            except Exception:
                continue

    # ==================== Click Final Create ====================

    async def _click_final_create(self, page) -> bool:
        """يضغط Create النهائي"""
        for sel in [
            'button:has-text("Create")',
            'button:has-text("Deploy")',
            '[role="button"]:has-text("Create")',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    # ✅ نتحقق أنه ماشي "Cancel"
                    txt = (await el.inner_text()).strip().lower()
                    if 'cancel' in txt:
                        continue
                    log.info(f"✅ Create: {sel}")
                    await el.click(timeout=5000)
                    return True
            except Exception:
                continue
        return False

    # ==================== Wait for Deployment ====================

    async def _wait_for_deployment(self, page, timeout: int = 300) -> str:
        """ينتظر النشر ويرجع URL"""
        log.info(f"⏳ ننتظر {timeout}s...")
        for i in range(timeout // 5):
            await asyncio.sleep(5)
            try:
                # ✅ نتحقق واش ظهر URL
                url = await page.evaluate("""
                    () => {
                        // ✅ نلقاو رابط .run.app
                        const links = document.querySelectorAll('a[href*=".run.app"]');
                        for (const a of links) {
                            if (a.href && a.href.includes('.run.app')) return a.href;
                        }
                        // ✅ من الـ body text
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
