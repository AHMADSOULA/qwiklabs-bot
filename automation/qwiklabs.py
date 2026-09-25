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

    async def check_sso_valid(self, page) -> tuple:
        """
        يتحقق من صلاحية SSO.
        يرجع (is_valid: bool, reason: str)
        """
        log.info("🔍 نتحقق من صلاحية SSO...")

        try:
            url = page.url.lower()
            content = (await page.content()).lower()
            text = (await page.inner_text("body")).lower()

            # ✅ 1. صفحة منتهية
            expired_keywords = [
                "this lab is expired",
                "lab has expired",
                "lab expired",
                "session has expired",
                "session expired",
                "this session has ended",
                "lab is no longer available",
                "cannot access",
                "الرابط منتهي",
            ]
            for kw in expired_keywords:
                if kw in content or kw in text:
                    return False, "⏰ الرابط منتهي الصلاحية"

            # ✅ 2. صفحة Sign in (ماشي SSO صحيح)
            if "accounts.google.com" in url and "addsession" in url:
                return False, "⚠️ الرابط ماشي SSO — هو Sign in مباشر"

            # ✅ 3. صفحة SSO صحيحة
            if "skills.google" in url or "qwiklabs" in url:
                # ✅ نتحقق واش فيه email
                m = re.search(r'Email=([^&\s#]+@qwiklabs\.net)', page.url)
                if m:
                    log.info(f"✅ SSO صالح — email: {m.group(1)}")
                    return True, f"✅ SSO صالح ({m.group(1)})"

            # ✅ 4. صفحة فاضية / خطأ
            if "not found" in text or "404" in text:
                return False, "❌ الصفحة ماشي موجودة (404)"

            # ✅ 5. إذا وصلنا لـ Lab (فيها credentials)
            if "@qwiklabs.net" in content:
                return True, "✅ SSO صالح — Lab page"

            return True, "✅ SSO مقبول"

        except Exception as e:
            log.warning(f"فشل التحقق: {e}")
            return True, f"⚠️ ما قدرناش نتحقق: {e}"

    async def extract_credentials(self, page):
        """يستخرج email + password (إذا موجود)"""
        log.info("استخراج credentials...")

        email = None
        password = None

        # email من URL
        m = re.search(r'Email=([^&\s#]+@qwiklabs\.net)', page.url)
        if m:
            email = m.group(1)
            log.info(f"✅ email من URL: {email}")

        # email من selectors
        if not email:
            for sel in ['[data-test-id="student-username"]', '.student-username', '#student-username']:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        email = (await el.inner_text()).strip()
                        break
                except Exception:
                    continue

        # email من HTML
        if not email:
            try:
                content = await page.content()
                m = re.search(r'([a-zA-Z0-9\.\-]+@qwiklabs\.net)', content)
                if m:
                    email = m.group(1)
            except Exception:
                pass

        # password من URL
        m = re.search(r'Password=([^&\s#]+)', page.url)
        if m:
            password = m.group(1)

        # password من selectors
        if not password:
            for sel in ['[data-test-id="student-password"]', '.student-password', '#student-password']:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        password = (await el.inner_text()).strip()
                        break
                except Exception:
                    continue

        # password من HTML
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
