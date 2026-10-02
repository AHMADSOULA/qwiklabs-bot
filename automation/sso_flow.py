"""
automation/sso_flow.py
تنسيق العملية الكاملة:
1. استقبال SSO link
2. فتح المتصفح
3. استخراج project_id + authuser
4. تنفيذ كل خطوات Cloud Run
5. إرجاع run.app URL
"""
import asyncio
import re
from urllib.parse import urlparse, parse_qs

from automation.deployer import CloudRunDeployer, extract_project_id
from utils.logger import get_logger
from utils.helpers import human_delay

log = get_logger("SSOFlow")


def extract_authuser(page_url: str) -> str:
    try:
        qs = parse_qs(urlparse(page_url).query)
        return qs.get('authuser', ['1'])[0]
    except Exception:
        return '1'


async def run_sso_flow(context, sso_url: str, sender=None, chat_id=None) -> dict:
    """
    ينفذ العملية كاملة ويرجع dict فيه:
    {
      "project_id": ...,
      "authuser": ...,
      "final_url": ...,
      "domain": ...,
    }
    """
    project_id = extract_project_id(sso_url)
    if not project_id:
        raise RuntimeError("❌ Project ID ماكانش في الرابط.")

    log.info(f"🚀 بدء SSO flow — project={project_id}")

    page = await context.new_page()

    try:
        await page.goto(sso_url, wait_until="domcontentloaded", timeout=60000)

        if sender:
            await sender.reply_text("🔄 𝙎𝙩𝙚𝙥 𝙤𝙣𝙚: فتح SSO...")

        # نستناو الداشبورد (بعد TOS + Terms Dialog)
        # ولكن Deployer رايح يعالجهم
        deployer = CloudRunDeployer(page, chat_id=chat_id, sender=sender)

        # ✅ نبداو بالخطوات — Deployer رايح يعالج TOS + Dialog + API + Cloud Run
        # نأخذو authuser من URL الحالي
        # ملاحظة: الخطوات 3+ خاصها authuser، نجيبوه بعد ما نعالجو TOS
        await deployer.step1_welcome_screen()
        await page.wait_for_timeout(3000)
        await deployer.step2_terms_dialog()

        # نستناو Dashboard
        if sender:
            await sender.reply_text("⏳ 𝙩𝙖𝙠𝙞𝙣𝙜 𝙖 𝙘𝙞𝙜𝙖𝙧𝙚𝙩𝙩𝙚 𝙛𝙞𝙧𝙨𝙩...")
        try:
            await page.wait_for_url("**/home/dashboard**", timeout=45000)
        except Exception:
            log.warning("⚠️ ما وصلناش Dashboard — نكملو بالقوة")

        authuser = extract_authuser(page.url)
        log.info(f"🔑 authuser = {authuser}")

        if sender:
            await sender.reply_text("🔄 𝙎𝙩𝙚𝙥 𝙩𝙬𝙤: تفعيل API...")

        await deployer.step3_enable_api(project_id, authuser)

        if sender:
            await sender.reply_text("🔄 𝙎𝙩𝙚𝙥 𝙩𝙝𝙧𝙚𝙚: إنشاء Cloud Run...")

        await deployer.step4_create_cloud_run(project_id, authuser)

        if sender:
            await sender.reply_text("⏳ 𝙬𝙖𝙞𝙩, 𝙟𝙪𝙨𝙩 𝙤𝙣𝙚 𝙘𝙞𝙜𝙖𝙧𝙚𝙩𝙩𝙚...")

        final_url = await deployer.step5_get_deployed_url()

        from automation.deployer import extract_domain_from_service_url
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
