"""
automation/sso_flow.py
تنسيق العملية الكاملة — بطريقة GC.py
"""
import re
from urllib.parse import urlparse, parse_qs

from automation.cloud_console import CloudConsole
from utils.logger import get_logger

log = get_logger("SSOFlow")


def extract_project_id(url: str) -> str:
    m = re.search(r'(qwiklabs-gcp-[\w-]+)', url or "")
    return m.group(1) if m else None


def extract_domain_from_service_url(service_url: str) -> str:
    s = (service_url or "").strip()
    if s.startswith("http://") or s.startswith("https://"):
        return urlparse(s).netloc.strip()
    return s.replace("http://", "").replace("https://", "").split("/")[0].strip()


def extract_authuser(page_url: str) -> str:
    try:
        qs = parse_qs(urlparse(page_url).query)
        return qs.get('authuser', ['1'])[0]
    except Exception:
        return '1'


async def run_sso_flow(context, sso_url: str) -> dict:
    """ينفذ العملية كاملة"""
    project_id = extract_project_id(sso_url)
    if not project_id:
        raise RuntimeError("❌ Project ID ماكانش في الرابط.")

    log.info(f"🚀 SSO flow — project={project_id}")

    page = await context.new_page()

    try:
        await page.goto(sso_url, wait_until="domcontentloaded", timeout=60000)

        console = CloudConsole(context)

        # STEP 1: TOS الأولى
        await console.step1_welcome_screen(page)

        # STEP 2: Terms Dialog
        await page.wait_for_timeout(3000)
        await console.step2_terms_dialog(page)

        # نستناو Dashboard
        try:
            await page.wait_for_url("**/home/dashboard**", timeout=45000)
        except Exception:
            log.warning("⚠️ ما وصلناش Dashboard — نكملو")

        authuser = extract_authuser(page.url)
        log.info(f"🔑 authuser = {authuser}")

        # STEP 3
        await console.step3_enable_api(page, project_id, authuser)

        # STEP 4
        await console.step4_create_cloud_run(page, project_id, authuser)

        # STEP 5
        final_url = await console.step5_get_deployed_url(page)
        domain = extract_domain_from_service_url(final_url)

        return {
            "project_id": project_id,
            "authuser": authuser,
            "final_url": final_url,
            "domain": domain,
        }

    finally:
        try:
            await page.close()
        except Exception:
            pass
