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
        log.info(f"URL: {sso_url[:120]}")

        try:
            await page.goto(sso_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log.warning(f"فشل التحميل الأول: {e}")
            try:
                await page.goto(sso_url, wait_until="load", timeout=60000)
            except Exception as e2:
                log.error(f"فشل مرة ثانية: {e2}")
                raise RuntimeError(f"ما قدرتش نفتح SSO: {e2}")

        # ✅ استنى طويل باش الصفحة تكمل
        await human_delay(8, 12)

        # ✅ انتظر حتى تظهر أي عناصر مهمة
        try:
            await page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass

        await take_screenshot(page, "01_sso_opened")
        log.info(f"URL بعد التحميل: {page.url}")
        log.info(f"Title: {await page.title()}")

        return page

    async def extract_credentials(self, page):
        """
        يستخرج email + password.
        password ممكن None.
        """
        log.info("استخراج credentials...")
        await take_screenshot(page, "02_before_extract")

        email = None
        password = None

        # ✅ نستنى باش الصفحة تكمل
        await human_delay(3, 5)

        # 🔍 نسجل نص الصفحة للتصحيح
        try:
            body_text = await page.inner_text("body")
            body_text = body_text[:600].replace('\n', ' | ')
            log.info(f"📄 نص الصفحة: {body_text[:400]}")
        except Exception as e:
            log.warning(f"فشل قراءة النص: {e}")

        # 🔍 نسجل URL الحالي
        current_url = page.url
        log.info(f"🔗 URL الحالي: {current_url}")

        # ========== 1. Email من URL ==========
        # Example: Email=student-02-xxx@qwiklabs.net
        m = re.search(r'Email=([^&\s#]+@qwiklabs\.net)', current_url)
        if m:
            email = m.group(1)
            log.info(f"✅ email من URL: {email}")

        # ========== 2. Email من selectors ==========
        if not email:
            for sel in [
                '[data-test-id="student-username"]',
                '[data-test-id="username"]',
                '.student-username',
                '#student-username',
                'span[data-test-id*="username" i]',
                'div[data-test-id*="username" i]',
            ]:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        text = (await el.inner_text()).strip()
                        if text and "@" in text:
                            email = text
                            log.info(f"✅ email من selector {sel}: {email}")
                            break
                except Exception:
                    continue

        # ========== 3. Email من HTML (regex) ==========
        if not email:
            try:
                content = await page.content()
                m = re.search(r'([a-zA-Z0-9\.\-]+@qwiklabs\.net)', content)
                if m:
                    email = m.group(1)
                    log.info(f"✅ email من HTML: {email}")
            except Exception as e:
                log.warning(f"فشل HTML: {e}")

        # ========== 4. Email من body text ==========
        if not email:
            try:
                body_text = await page.inner_text("body")
                m = re.search(r'([a-zA-Z0-9\.\-]+@qwiklabs\.net)', body_text)
                if m:
                    email = m.group(1)
                    log.info(f"✅ email من body: {email}")
            except Exception:
                pass

        # ========== 5. Password من selectors ==========
        for sel in [
            '[data-test-id="student-password"]',
            '[data-test-id="password"]',
            '.student-password',
            '#student-password',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    text = (await el.inner_text()).strip()
                    if text:
                        password = text
                        log.info(f"✅ password من selector")
                        break
            except Exception:
                continue

        # ========== 6. Password من URL ==========
        if not password:
            m = re.search(r'Password=([^&\s#]+)', current_url)
            if m:
                password = m.group(1)
                log.info(f"✅ password من URL")

        # ========== 7. Password من HTML ==========
        if not password:
            try:
                content = await page.content()
                m = re.search(r'"password"\s*:\s*"([^"]+)"', content)
                if m:
                    password = m.group(1)
                    log.info(f"✅ password من JSON")
            except Exception:
                pass

        await take_screenshot(page, "03_extracted")

        # ✅ إذا ما لقيناش email → خطأ
        if not email:
            # 📸 Screenshot إضافي للتصحيح
            await take_screenshot(page, "03_no_email")

            # نحفظ HTML
            try:
                html = await page.content()
                with open("/app/data/screenshots/no_email_dump.html", "w", encoding="utf-8") as f:
                    f.write(html)
            except Exception:
                pass

            # نحفظ نص الصفحة
            try:
                body_text = await page.inner_text("body")
                body_text = body_text[:500].replace('\n', ' | ')
            except Exception:
                body_text = "ما قدرتش نقرا النص"

            raise RuntimeError(
                f"❌ فشل استخراج email\n"
                f"🔗 URL: {current_url[:180]}\n"
                f"📄 النص: {body_text[:200]}"
            )

        log.info(f"✅ email: {email}")
        log.info(f"✅ password: {'✅ موجود' if password else '❌ ماكانش'}")
        return email, password
