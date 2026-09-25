import re
import asyncio
from utils.logger import get_logger
from utils.helpers import human_delay
from utils.screenshot import take_screenshot

log = get_logger("QwikLabs")


class QwikLabsSession:
    def __init__(self, context):
        self.context = context

    async def open_sso(self, sso_url: str):
        page = await self.context.new_page()
        log.info(f"فتح SSO...")
        try:
            await page.goto(sso_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log.warning(f"فشل: {e}")
            await page.goto(sso_url, wait_until="load", timeout=60000)

        await human_delay(8, 12)
        await take_screenshot(page, "01_initial")
        log.info(f"URL: {page.url}")

        for i in range(18):
            await asyncio.sleep(5)
            current_url = page.url
            if "qwiklabs" in current_url.lower() or "@qwiklabs.net" in current_url:
                log.info(f"✅ Qwiklabs")
                break
            try:
                content = await page.content()
                if "@qwiklabs.net" in content:
                    break
            except Exception:
                pass

        await take_screenshot(page, "01_sso_opened")
        return page

    async def extract_credentials(self, page):
        log.info("استخراج credentials...")
        await take_screenshot(page, "02_before_extract")

        email = None
        password = None

        await human_delay(5, 8)
        current_url = page.url

        m = re.search(r'Email=([^&\s#]+@qwiklabs\.net)', current_url)
        if m:
            email = m.group(1)
            log.info(f"✅ email URL: {email}")

        if not email:
            try:
                content = await page.content()
                m = re.search(r'([a-zA-Z0-9\.\-]+@qwiklabs\.net)', content)
                if m:
                    email = m.group(1)
            except Exception:
                pass

        if not email:
            try:
                body = await page.inner_text("body")
                m = re.search(r'([a-zA-Z0-9\.\-]+@qwiklabs\.net)', body)
                if m:
                    email = m.group(1)
            except Exception:
                pass

        m = re.search(r'Password=([^&\s#]+)', current_url)
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

        await take_screenshot(page, "03_extracted")

        if not email:
            await take_screenshot(page, "03_no_email")
            try:
                body = await page.inner_text("body")
                body = body[:400].replace('\n', ' | ')
            except Exception:
                body = ""
            raise RuntimeError(
                f"❌ فشل email\n🔗 {current_url[:180]}\n📄 {body[:200]}"
            )

        log.info(f"✅ email: {email}")
        log.info(f"✅ pass: {'✅' if password else '❌'}")
        return email, password
