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
        log.info("استخراج credentials...")
        username = None
        password = None

        selectors_username = [
            '[data-test-id="student-username"]',
            '.student-username',
            '#student-username',
        ]
        selectors_password = [
            '[data-test-id="student-password"]',
            '.student-password',
            '#student-password',
        ]

        try:
            show_btn = page.locator('button:has-text("Show"), button:has-text("Open")').first
            if await show_btn.count() > 0:
                await human_move(page)
                await show_btn.click()
                await human_delay(1, 2)
        except Exception:
            pass

        for sel in selectors_username:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    username = (await el.inner_text()).strip()
                    break
            except Exception:
                continue

        for sel in selectors_password:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    password = (await el.inner_text()).strip()
                    break
            except Exception:
                continue

        if not username or not password:
            content = await page.content()
            import re
            m_user = re.search(r'([\w\.\-]+@qwiklabs\.net)', content)
            if m_user and not username:
                username = m_user.group(1)

        if not username or not password:
            raise RuntimeError("فشل استخراج credentials")

        log.info(f"تم استخراج credentials: {username}")
        return username, password
