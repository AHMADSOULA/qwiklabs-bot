import re
from utils.logger import get_logger
from utils.helpers import human_delay, human_move

log = get_logger("QwikLabs")


class QwikLabsSession:
    def __init__(self, context):
        self.context = context

    async def open_sso(self, sso_url: str):
        page = await self.context.new_page()
        log.info(f"فتح SSO: {sso_url[:80]}...")
        await page.goto(sso_url, wait_until="domcontentloaded")
        await human_delay(4, 7)
        return page

    async def extract_credentials(self, page):
        """
        يستخرج email + password (إذا موجود).
        ✅ ما يفشلش إذا ما لقاش password — يرجع None.
        """
        log.info("استخراج credentials...")
        username = None
        password = None

        # ============================================
        # ✅ 1. Email من URL
        # ============================================
        m = re.search(r'Email=([^&\s#]+@qwiklabs\.net)', page.url)
        if m:
            username = m.group(1)
            log.info(f"✅ email من URL: {username}")

        # ============================================
        # ✅ 2. Email من selectors
        # ============================================
        if not username:
            for sel in [
                '[data-test-id="student-username"]',
                '.student-username',
                '#student-username',
            ]:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        username = (await el.inner_text()).strip()
                        break
                except Exception:
                    continue

        # ============================================
        # ✅ 3. Email من HTML
        # ============================================
        if not username:
            try:
                content = await page.content()
                m = re.search(r'([\w\.\-]+@qwiklabs\.net)', content)
                if m:
                    username = m.group(1)
            except Exception:
                pass

        # ============================================
        # ✅ 4. Password من URL
        # ============================================
        m = re.search(r'Password=([^&\s#]+)', page.url)
        if m:
            password = m.group(1)
            log.info(f"✅ password من URL")

        # ============================================
        # ✅ 5. Password من selectors
        # ============================================
        if not password:
            for sel in [
                '[data-test-id="student-password"]',
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

        # ============================================
        # ✅ 6. Password من HTML
        # ============================================
        if not password:
            try:
                content = await page.content()
                m = re.search(r'"password"\s*:\s*"([^"]+)"', content)
                if m:
                    password = m.group(1)
            except Exception:
                pass

        # ============================================
        # ✅ 7. إذا ما لقيناش email → فشل
        # ============================================
        if not username:
            raise RuntimeError("فشل استخراج email")

        # ============================================
        # ✅ 8. إذا ما لقيناش password → نرجعو None
        #    (البوت غادي يطلبو من المستخدم)
        # ============================================
        if not password:
            log.info("⚠️ ما لقيناش password — البوت غادي يطلبو")
        else:
            log.info(f"✅ email: {username}, password: ✅")

        return username, password
