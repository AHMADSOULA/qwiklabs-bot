from utils.logger import get_logger
from utils.helpers import human_delay, human_move
from utils.screenshot import take_screenshot

log = get_logger("QwikLabs")


class QwikLabsSession:
    def __init__(self, context):
        self.context = context

    async def open_sso(self, sso_url: str):
        page = await self.context.new_page()
        log.info(f"فتح رابط SSO...")
        await page.goto(sso_url, wait_until="domcontentloaded")
        await human_delay(5, 8)
        await take_screenshot(page, "01_sso_opened")
        log.info(f"URL: {page.url}")
        return page

    async def extract_credentials(self, page):
        """
        يستخرج username فقط.
        Password كيتعرضش فـ HTML — خاص المستخدم يرسلو.
        """
        log.info("استخراج username من صفحة Lab...")
        await take_screenshot(page, "02_before_extract")

        username = None

        # 1. نحاول من selectors
        selectors = [
            '[data-test-id="student-username"]',
            '[data-test-id="username"]',
            '.student-username',
            '#student-username',
        ]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    username = (await el.inner_text()).strip()
                    break
            except Exception:
                continue

        # 2. من URL (Email=xxx@qwiklabs.net)
        if not username:
            import re
            url = page.url
            m = re.search(r'Email=([^&\s]+@qwiklabs\.net)', url)
            if m:
                username = m.group(1)
                log.info(f"✅ username من URL: {username}")

        # 3. من HTML
        if not username:
            content = await page.content()
            import re
            m = re.search(r'([a-zA-Z0-9\.\-]+@qwiklabs\.net)', content)
            if m:
                username = m.group(1)
                log.info(f"✅ username من HTML")

        await take_screenshot(page, "03_extracted")

        if not username:
            raise RuntimeError("فشل استخراج username")

        log.info(f"✅ username: {username}")
        return username
