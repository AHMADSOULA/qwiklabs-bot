import re
from utils.logger import get_logger
from utils.helpers import human_delay

log = get_logger("QwikLabs")


class QwikLabsSession:
    def __init__(self, context):
        self.context = context

    async def open_sso(self, sso_url: str):
        page = await self.context.new_page()
        log.info(f"فتح SSO: {sso_url[:100]}")
        try:
            await page.goto(sso_url, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            await page.goto(sso_url, wait_until="load", timeout=60000)
        await human_delay(5, 8)
        return page

    async def extract_credentials(self, page):
        log.info("استخراج credentials...")
        email = None
        password = None

        m = re.search(r'Email=([^&\s#]+@qwiklabs\.net)', page.url)
        if m:
            email = m.group(1)

        if not email:
            try:
                content = await page.content()
                m = re.search(r'([a-zA-Z0-9\.\-]+@qwiklabs\.net)', content)
                if m:
                    email = m.group(1)
            except Exception:
                pass

        m = re.search(r'Password=([^&\s#]+)', page.url)
        if m:
            password = m.group(1)

        if not password:
            try:
                content = await page.content()
                m = re.search(r'"password"\s*:\s*"([^"]+)"', content)
                if m:
                    password = m.group(1)
            except Exception:
                pass

        if not email:
            raise RuntimeError("فشل استخراج email")

        log.info(f"✅ email: {email}, password: {'✅' if password else '❌'}")
        return email, password
