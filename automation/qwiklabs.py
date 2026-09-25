import re
import asyncio
from utils.logger import get_logger
from utils.helpers import human_delay, human_move
from utils.screenshot import take_screenshot

log = get_logger("QwikLabs")


class QwikLabsSession:
    def __init__(self, context):
        self.context = context

    async def open_sso(self, sso_url: str):
        page = await self.context.new_page()
        log.info("فتح SSO...")
        log.info(f"URL: {sso_url[:120]}")

        try:
            await page.goto(sso_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log.warning(f"فشل التحميل الأول: {e}")
            try:
                await page.goto(sso_url, wait_until="load", timeout=60000)
            except Exception as e2:
                raise RuntimeError(f"ما قدرتش نفتح SSO: {e2}")

        # ✅ نستنى redirects
        await human_delay(8, 12)
        await take_screenshot(page, "01_initial")
        log.info(f"URL أولي: {page.url}")

        # ✅ ننتظر حتى يوصل لـ Qwiklabs
        for i in range(18):
            await asyncio.sleep(5)
            current_url = page.url
            if "qwiklabs" in current_url.lower() or "@qwiklabs.net" in current_url:
                log.info(f"✅ وصلنا لـ Qwiklabs")
                break
            try:
                content = await page.content()
                if "@qwiklabs.net" in content:
                    log.info(f"✅ لقيت email فـ HTML")
                    break
            except Exception:
                pass

        await take_screenshot(page, "01_sso_opened")
        log.info(f"URL نهائي: {page.url}")
        return page

    async def extract_credentials(self, page):
        log.info("استخراج credentials...")
        await take_screenshot(page, "02_before_extract")

        email = None
        password = None

        await human_delay(5, 8)

        current_url = page.url
        log.info(f"🔗 URL: {current_url}")

        # 1. Email من URL
        m = re.search(r'Email=([^&\s#]+@qwiklabs\.net)', current_url)
        if m:
            email = m.group(1)
            log.info(f"✅ email من URL: {email}")

        # 2. Email من HTML
        if not email:
            try:
                content = await page.content()
                m = re.search(r'([a-zA-Z0-9\.\-]+@qwiklabs\.net)', content)
                if m:
                    email = m.group(1)
                    log.info(f"✅ email من HTML: {email}")
            except Exception:
                pass

        # 3. Email من body
        if not email:
            try:
                body = await page.inner_text("body")
                m = re.search(r'([a-zA-Z0-9\.\-]+@qwiklabs\.net)', body)
                if m:
                    email = m.group(1)
            except Exception:
                pass

        # 4. Password من URL
        m = re.search(r'Password=([^&\s#]+)', current_url)
        if m:
            password = m.group(1)

        # 5. Password من HTML
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
                body = "ما قدرتش نقرا"

            raise RuntimeError(
                f"❌ فشل استخراج email\n\n"
                f"🔗 URL: {current_url[:180]}\n\n"
                f"📄 النص: {body[:200]}"
            )

        log.info(f"✅ email: {email}")
        log.info(f"✅ password: {'✅' if password else '❌'}")
        return email, password
