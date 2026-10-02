"""
automation/sso_flow.py
تنسيق العملية الكاملة — بلا تصوير
"""
import re
from urllib.parse import urlparse, parse_qs

from automation.deployer import CloudRunDeployer, extract_project_id, extract_domain_from_service_url
from utils.logger import get_logger

log = get_logger("SSOFlow")


def extract_authuser(page_url: str) -> str:
    try:
        qs = parse_qs(urlparse(page_url).query)
        return qs.get('authuser', ['1'])[0]
    except Exception:
        return '1'


async def run_sso_flow(context, sso_url: str) -> dict:
    """ينفذ العملية كاملة ويرجع dict فيه final_url + domain"""
    project_id = extract_project_id(sso_url)
    if not project_id:
        raise RuntimeError("❌ Project ID ماكانش في الرابط.")

    log.info(f"🚀 SSO flow — project={project_id}")

    page = await context.new_page()

    try:
        await page.goto(sso_url, wait_until="domcontentloaded", timeout=60000)

        deployer = CloudRunDeployer(page)

        # STEP 1
        await deployer.step1_welcome_screen()

        # STEP 2
        await page.wait_for_timeout(3000)
        await deployer.step2_terms_dialog()

        # Dashboard
        try:
            await page.wait_for_url("**/home/dashboard**", timeout=45000)
        except Exception:
            log.warning("⚠️ ما وصلناش Dashboard — نكملو")

        authuser = extract_authuser(page.url)
        log.info(f"🔑 authuser = {authuser}")

        # STEP 3
        await deployer.step3_enable_api(project_id, authuser)

        # STEP 4
        await deployer.step4_create_cloud_run(project_id, authuser)

        # STEP 5
        final_url = await deployer.step5_get_deployed_url()
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
