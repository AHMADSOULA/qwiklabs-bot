from utils.logger import get_logger
from utils.helpers import human_delay, human_move
from utils.screenshot import take_screenshot

log = get_logger("QwikLabs")


class QwikLabsSession:
    def __init__(self, context):
        self.context = context

    async def open_sso(self, sso_url: str):
        page = await self.context.new_page()
        log.info(f"فتح رابط SSO: {sso_url[:80]}...")
        await page.goto(sso_url, wait_until="domcontentloaded")
        await human_delay(5, 8)

        # 📸 Screenshot 1: بعد فتح SSO
        await take_screenshot(page, "01_sso_opened")
        log.info(f"URL الحالي: {page.url}")

        return page

    async def extract_credentials(self, page):
        log.info("استخراج credentials من صفحة Lab...")

        # 📸 Screenshot 2: قبل محاولة الاستخراج
        await take_screenshot(page, "02_before_extract")

        # نحاول نظغط على Show credentials
        try:
            buttons_to_try = [
                'button:has-text("Show")',
                'button:has-text("Open")',
                'button:has-text("Start Lab")',
                'button:has-text("Launch")',
            ]
            for selector in buttons_to_try:
                btn = page.locator(selector).first
                if await btn.count() > 0:
                    log.info(f"كليك على الزر: {selector}")
                    await human_move(page)
                    await btn.click()
                    await human_delay(3, 5)
                    break
        except Exception as e:
            log.warning(f"ما لقيتش زر Show/Open: {e}")

        # 📸 Screenshot 3: بعد الكليك
        await take_screenshot(page, "03_after_show_click")
        log.info(f"URL بعد الكليك: {page.url}")

        username = None
        password = None

        # المحاولة 1: selectors مباشرة
        selectors_username = [
            '[data-test-id="student-username"]',
            '[data-test-id="username"]',
            '.student-username',
            '#student-username',
            'span[data-test-id="student-username"]',
            'div[data-test-id="username"]',
        ]
        selectors_password = [
            '[data-test-id="student-password"]',
            '[data-test-id="password"]',
            '.student-password',
            '#student-password',
            'span[data-test-id="student-password"]',
            'div[data-test-id="password"]',
        ]

        for sel in selectors_username:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    username = (await el.inner_text()).strip()
                    log.info(f"✅ لقيت username بـ selector: {sel}")
                    break
            except Exception:
                continue

        for sel in selectors_password:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    password = (await el.inner_text()).strip()
                    log.info(f"✅ لقيت password بـ selector: {sel}")
                    break
            except Exception:
                continue

        # المحاولة 2: regex من HTML
        if not username or not password:
            log.info("المحاولة 2: regex من HTML")
            content = await page.content()
            import re

            if not username:
                m_user = re.search(r'([a-zA-Z0-9\.\-]+@qwiklabs\.net)', content)
                if m_user:
                    username = m_user.group(1)
                    log.info(f"✅ username من regex: {username}")

            if not password:
                # كلمة السر عادة مكونة من حروف وأرقام، 12-20 حرف
                m_pass = re.search(r'"password"\s*:\s*"([^"]+)"', content)
                if m_pass:
                    password = m_pass.group(1)
                    log.info(f"✅ password من JSON")

                if not password:
                    # طريقة أخرى: البحث عن نمط معين
                    m_pass2 = re.search(
                        r'password["\']?\s*[:=]\s*["\']([A-Za-z0-9]{12,25})["\']',
                        content
                    )
                    if m_pass2:
                        password = m_pass2.group(1)
                        log.info(f"✅ password من نمط 2")

        # 📸 Screenshot 4: قبل ما نقرر
        await take_screenshot(page, "04_extraction_result")

        if not username or not password:
            # احفظ HTML للتصحيح
            content = await page.content()
            with open("/app/data/screenshots/page_dump.html", "w", encoding="utf-8") as f:
                f.write(content)

            raise RuntimeError(
                f"فشل استخراج credentials\n"
                f"username: {username}\n"
                f"password: {'found' if password else 'NOT found'}"
            )

        log.info(f"✅ تم استخراج credentials: {username}")
        return username, password
