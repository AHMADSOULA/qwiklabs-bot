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

        # ✅ استنى طويل + redirects
        log.info("⏳ ننتظر redirects...")
        await human_delay(8, 12)
        await take_screenshot(page, "01_initial")
        log.info(f"URL أولي: {page.url}")

        # ✅ ننتظر حتى يوصل لـ Qwiklabs (max 90 ثانية)
        log.info("⏳ ننتظر Qwiklabs lab page...")
        for i in range(18):  # 18 × 5 = 90 ثانية
            await asyncio.sleep(5)

            try:
                await page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass

            current_url = page.url
            log.info(f"[{i+1}/18] URL: {current_url[:100]}")

            # ✅ إذا وصلنا لـ Qwiklabs
            if "qwiklabs" in current_url.lower() or "skills.google" in current_url.lower():
                log.info(f"✅ وصلنا لـ Qwiklabs!")
                break

            # ✅ إذا لقي email فـ URL
            if "@qwiklabs.net" in current_url:
                log.info(f"✅ لقيت email فـ URL!")
                break

            # ✅ نشوفو content
            try:
                content = await page.content()
                if "@qwiklabs.net" in content:
                    log.info(f"✅ لقيت email فـ HTML!")
                    break
                if "student" in content.lower() and "password" in content.lower():
                    log.info(f"✅ لقيت صفحة Lab!")
                    break
            except Exception:
                pass

        await take_screenshot(page, "01_sso_opened")
        log.info(f"URL نهائي: {page.url}")
        log.info(f"Title: {await page.title()}")

        return page

    async def extract_credentials(self, page):
        log.info("استخراج credentials...")
        await take_screenshot(page, "02_before_extract")

        email = None
        password = None

        # ✅ نستنى باش الصفحة تكمل
        await human_delay(5, 8)

        # 🔍 نسجل نص الصفحة
        try:
            body_text = await page.inner_text("body")
            body_text_short = body_text[:600].replace('\n', ' | ')
            log.info(f"📄 نص: {body_text_short[:400]}")
        except Exception as e:
            log.warning(f"فشل النص: {e}")
            body_text = ""

        current_url = page.url
        log.info(f"🔗 URL: {current_url}")

        # ✅ إعادة محاولة: إذا كنا فـ accounts.google.com، نستنى أكثر
        if "accounts.google.com" in current_url:
            log.info("⏳ لسه فـ Google Sign in — نستنى...")
            for i in range(12):  # 60 ثانية
                await asyncio.sleep(5)
                new_url = page.url
                log.info(f"[{i+1}/12] URL: {new_url[:100]}")
                if "accounts.google.com" not in new_url:
                    log.info(f"✅ خرجنا من Google Sign in")
                    break
                if "@qwiklabs.net" in new_url:
                    break
            await human_delay(3, 5)
            current_url = page.url
            log.info(f"🔗 URL بعد الانتظار: {current_url}")

        # ========== 1. Email من URL ==========
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
                        if text and "@" in text and "qwiklabs" in text:
                            email = text
                            log.info(f"✅ email من selector: {email}")
                            break
                except Exception:
                    continue

        # ========== 3. Email من HTML ==========
        if not email:
            try:
                content = await page.content()
                m = re.search(r'([a-zA-Z0-9\.\-]+@qwiklabs\.net)', content)
                if m:
                    email = m.group(1)
                    log.info(f"✅ email من HTML: {email}")
            except Exception:
                pass

        # ========== 4. Email من body ==========
        if not email and body_text:
            m = re.search(r'([a-zA-Z0-9\.\-]+@qwiklabs\.net)', body_text)
            if m:
                email = m.group(1)
                log.info(f"✅ email من body: {email}")

        # ========== 5. Password ==========
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

        if not password:
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

        # ❌ ما لقيناش email
        if not email:
            await take_screenshot(page, "03_no_email")

            try:
                html = await page.content()
                with open("/app/data/screenshots/no_email_dump.html", "w", encoding="utf-8") as f:
                    f.write(html)
            except Exception:
                pass

            try:
                body_text = await page.inner_text("body")
                body_text = body_text[:400].replace('\n', ' | ')
            except Exception:
                body_text = "ما قدرتش نقرا"

            raise RuntimeError(
                f"❌ فشل استخراج email\n\n"
                f"🔗 URL: {current_url[:180]}\n\n"
                f"📄 النص: {body_text[:200]}"
            )

        log.info(f"✅ email: {email}")
        log.info(f"✅ password: {'✅' if password else '❌'}")
        return email, password
