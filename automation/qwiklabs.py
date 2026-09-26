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
        """يتحقق من صلاحية SSO — يقبل AddSession أيضاً"""
        log.info("🔍 نتحقق من SSO...")

        try:
            url = page.url.lower()
            url_orig = page.url
            content = (await page.content()).lower()
            try:
                text = (await page.inner_text("body")).lower()
            except Exception:
                text = ""

            # ============================================
            # ✅ 1. AddSession — نقبلها أولاً (قبل أي فحص)
            # ============================================
            if "accounts.google.com" in url and "addsession" in url:
                m = re.search(r'Email=([^&\s#]+@qwiklabs\.net)', url_orig)
                if m:
                    email = m.group(1)
                    log.info(f"⚠️ AddSession مقبول — {email}")
                    return True, f"✅ SSO مقبول — {email}"
                log.info("⚠️ AddSession بلا Email — نقبلها مع ذلك")
                return True, "✅ AddSession مقبول"

            # ============================================
            # ✅ 2. Sign in مباشر (بلا Email)
            # ============================================
            if "accounts.google.com" in url and "signin" in url:
                if "email=" in url_orig.lower():
                    m = re.search(r'Email=([^&\s#]+@qwiklabs\.net)', url_orig)
                    if m:
                        return True, f"✅ Sign in مع Email — {m.group(1)}"
                log.info("⚠️ Sign in بلا Email — نقبلها")
                return True, "✅ Sign in مقبول"

            # ============================================
            # ✅ 3. فحص "منتهي" — بحذر
            # ============================================
            expired_kw = [
                "this lab is expired",
                "lab is expired",
                "lab has expired",
                "lab expired",
                "session has expired",
                "session expired",
                "this session has expired",
                "no longer available",
                "lab is no longer available",
                "الرابط منتهي",
                "انتهت الصلاحية",
            ]
            for kw in expired_kw:
                # ✅ نتحققو من نص الصفحة (ماشي URL)
                if kw in text or kw in content:
                    log.warning(f"⏰ كلمة منتهي: '{kw}'")
                    return False, "⏰ الرابط منتهي الصلاحية"

            # ============================================
            # ✅ 4. 404
            # ============================================
            if "404" in text and "not found" in text:
                return False, "❌ الصفحة غير موجودة"

            # ============================================
            # ✅ 5. SSO صحيح (skills.google/google_sso)
            # ============================================
            if "skills.google" in url and "google_sso" in url:
                m = re.search(r'Email=([^&\s#]+@qwiklabs\.net)', url_orig)
                if m:
                    return True, f"✅ SSO صالح — {m.group(1)}"
                return True, "✅ SSO صالح"

            # ============================================
            # ✅ 6. Email فـ URL
            # ============================================
            m = re.search(r'Email=([^&\s#]+@qwiklabs\.net)', url_orig)
            if m:
                return True, f"✅ SSO صالح — {m.group(1)}"

            # ============================================
            # ✅ 7. Email فـ content
            # ============================================
            if "@qwiklabs.net" in content:
                return True, "✅ SSO صالح — Lab page"

            log.info("✅ SSO مقبول (بلا تحقق قوي)")
            return True, "✅ SSO مقبول"

        except Exception as e:
            log.warning(f"فشل التحقق: {e}")
            return True, f"⚠️ ما قدرناش نتحقق: {str(e)[:100]}"

    async def extract_credentials(self, page):
        """يستخرج email + password"""
        log.info("استخراج credentials...")

        email = None
        password = None

        # email من URL
        m = re.search(r'Email=([^&\s#]+@qwiklabs\.net)', page.url)
        if m:
            email = m.group(1)
            log.info(f"✅ email من URL: {email}")

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
