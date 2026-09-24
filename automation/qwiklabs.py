import re
from utils.logger import get_logger
from utils.helpers import human_delay, human_move
from utils.screenshot import take_screenshot

log = get_logger("QwikLabs")


class QwikLabsSession:
    def __init__(self, context):
        self.context = context

    async def open_sso(self, sso_url: str):
        page = await self.context.new_page()
        log.info("فتح رابط SSO...")
        await page.goto(sso_url, wait_until="domcontentloaded")
        await human_delay(5, 8)
        await take_screenshot(page, "01_sso_opened")
        log.info(f"URL: {page.url}")
        return page

    async def extract_credentials(self, page):
        """
        يستخرج email + password (إذا كانو موجودين).
        password ممكن يكون None إذا SSO فيه غير email.
        """
        log.info("استخراج credentials...")
        await take_screenshot(page, "02_before_extract")

        email = None
        password = None

        # 1. email من selectors
        for sel in [
            '[data-test-id="student-username"]',
            '[data-test-id="username"]',
            '.student-username',
            '#student-username',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    email = (await el.inner_text()).strip()
                    break
            except Exception:
                continue

        # 2. email من URL
        if not email:
            url = page.url
            m = re.search(r'Email=([^&\s]+@qwiklabs\.net)', url)
            if m:
                email = m.group(1)
                log.info(f"✅ email من URL: {email}")

        # 3. email من HTML
        if not email:
            content = await page.content()
            m = re.search(r'([a-zA-Z0-9\.\-]+@qwiklabs\.net)', content)
            if m:
                email = m.group(1)

        # 4. password من selectors
        for sel in [
            '[data-test-id="student-password"]',
            '[data-test-id="password"]',
            '.student-password',
            '#student-password',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    password = (await el.inner_text()).strip()
                    break
            except Exception:
                continue

        # 5. password من URL
        if not password:
            url = page.url
            m = re.search(r'Password=([^&\s]+)', url)
            if m:
                password = m.group(1)
                log.info(f"✅ password من URL")

        # 6. password من HTML (JSON)
        if not password:
            content = await page.content()
            m = re.search(r'"password"\s*:\s*"([^"]+)"', content)
            if m:
                password = m.group(1)
                log.info(f"✅ password من JSON")

        await take_screenshot(page, "03_extracted")

        if not email:
            raise RuntimeError("فشل استخراج email")

        log.info(f"✅ email: {email}")
        log.info(f"✅ password: {'✅ موجود' if password else '❌ ماكانش'}")
        return email, password
