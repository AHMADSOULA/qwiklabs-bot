import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from bot import messages
from bot.keyboards import main_menu
from database import db
from utils.helpers import extract_urls
from utils.logger import get_logger
from automation.browser import StealthBrowser
from automation.qwiklabs import QwikLabsSession
from automation.cloud_console import CloudConsole

log = get_logger("Handlers")
job_lock = asyncio.Lock()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.register_user(user.id, user.username or user.first_name)
    await update.message.reply_text(
        messages.WELCOME, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu()
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(messages.WELCOME, parse_mode=ParseMode.MARKDOWN)


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    jobs = await db.get_user_jobs(user.id, limit=5)
    if not jobs:
        await update.message.reply_text("📭 لا توجد مهام سابقة.")
        return
    lines = []
    for jid, status, created in jobs:
        emoji = {"pending": "⏳", "done": "✅", "failed": "❌"}.get(status, "❔")
        lines.append(messages.JOB_LINE.format(
            id=jid, status_emoji=emoji, status=status, date=created
        ))
    await update.message.reply_text(
        messages.STATUS_TEMPLATE.format(count=len(jobs), jobs="\n".join(lines)),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 تم الإلغاء.")


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    urls = extract_urls(text)
    if not urls:
        await update.message.reply_text(messages.NO_URL)
        return
    sso_url = urls[0]
    user = update.effective_user
    if "skills.google" not in sso_url and "qwiklabs" not in sso_url:
        await update.message.reply_text("⚠️ الرابط لا يبدو من Google Skills.")
        return
    job_id = await db.add_job(user.id, sso_url)
    msg = await update.message.reply_text(
        f"📥 تم استلام المهمة `#{job_id}`\n\n{messages.PROCESSING}",
        parse_mode=ParseMode.MARKDOWN,
    )
    asyncio.create_task(run_job(job_id, sso_url, msg))


async def run_job(job_id, sso_url, msg):
    async with job_lock:
        browser = StealthBrowser()
        try:
            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n🔹 إطلاق المتصفح المخفي...",
                parse_mode=ParseMode.MARKDOWN,
            )
            ctx = await browser.start()

            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n🔹 فتح رابط SSO...",
                parse_mode=ParseMode.MARKDOWN,
            )
            ql = QwikLabsSession(ctx)
            page = await ql.open_sso(sso_url)

            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n🔹 استخراج بيانات الدخول...",
                parse_mode=ParseMode.MARKDOWN,
            )
            username, password = await ql.extract_credentials(page)

            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n🔹 تسجيل الدخول لـ Cloud Console...",
                parse_mode=ParseMode.MARKDOWN,
            )
            cc = CloudConsole(ctx)
            console_page = await cc.login(username, password)

            project_id = await get_project_id(console_page)
            if not project_id:
                raise RuntimeError("تعذر استخراج project ID من Cloud Console")

            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n"
                f"🔹 استخراج access token...\n"
                f"📦 المشروع: `{project_id}`",
                parse_mode=ParseMode.MARKDOWN,
            )

            from automation.cloudrun_deployer import CloudRunDeployer, extract_access_token
            token = await extract_access_token(console_page)

            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n"
                f"🔹 نشر `ahmed-vip1` على Cloud Run...\n"
                f"⏳ قد يستغرق 1-3 دقائق\n"
                f"📦 `{project_id}`",
                parse_mode=ParseMode.MARKDOWN,
            )

            deployer = CloudRunDeployer(
                access_token=token,
                project_id=project_id,
                region="us-central1",
            )

            url = await deployer.deploy(
                service_name="ahmed-vip1",
                image="docker.io/ajndjd2/ahmed-vip1",
                memory="4Gi",
                cpu="2",
                port=8080,
                allow_unauthenticated=True,
            )

            await db.update_job(job_id, "done", url)
            await msg.edit_text(
                f"✅ *#{job_id}* — تم النشر بنجاح!\n\n"
                f"🔗 *الرابط:*\n{url}\n\n"
                f"👤 `{username}`\n"
                f"📦 `{project_id}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            log.exception("فشل تنفيذ المهمة")
            await db.update_job(job_id, "failed", str(e))
            await msg.edit_text(
                messages.FAILED.format(error=str(e)[:300]),
                parse_mode=ParseMode.MARKDOWN,
            )
        finally:
            await browser.close()


async def get_project_id(page) -> str:
    import re
    url = page.url
    m = re.search(r'project=([a-z0-9\-]+)', url)
    if m:
        return m.group(1)
    try:
        pid = await page.evaluate("""
            () => {
                if (window._gcp_project) return window._gcp_project;
                const el = document.querySelector('[data-project-id]');
                if (el) return el.getAttribute('data-project-id');
                return null;
            }
        """)
        return pid
    except Exception:
        return None


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "status":
        await status_cmd(update, context)
    elif query.data == "help":
        await query.message.reply_text(messages.WELCOME, parse_mode=ParseMode.MARKDOWN)
