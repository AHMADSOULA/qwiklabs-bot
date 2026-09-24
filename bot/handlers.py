import asyncio
import re
from telegram import Update, InputFile
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from bot import messages
from bot.keyboards import (
    main_menu, region_menu, memory_menu, cpu_menu, confirm_menu
)
from database import db
from utils.helpers import extract_urls
from utils.logger import get_logger
from utils.screenshot import take_screenshot
from automation.browser import StealthBrowser
from automation.qwiklabs import QwikLabsSession
from automation.cloud_console import CloudConsole

log = get_logger("Handlers")
job_lock = asyncio.Lock()


# ==================== أوامر ====================

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
        emoji = {"pending": "⏳", "done": "✅", "failed": "❌",
                 "waiting_password": "🔑"}.get(status, "❔")
        lines.append(messages.JOB_LINE.format(
            id=jid, status_emoji=emoji, status=status, date=created
        ))
    await update.message.reply_text(
        messages.STATUS_TEMPLATE.format(count=len(jobs), jobs="\n".join(lines)),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.clear_session(user.id)
    b = context.bot_data.pop(f"browser_{user.id}", None)
    context.bot_data.pop(f"page_{user.id}", None)
    context.bot_data.pop(f"ctx_{user.id}", None)
    if b:
        try:
            await b.close()
        except Exception:
            pass
    await update.message.reply_text("🚫 تم الإلغاء.")


async def send_photo(msg, filepath, caption=""):
    try:
        if not filepath:
            return
        with open(filepath, "rb") as f:
            await msg.reply_photo(photo=InputFile(f), caption=caption[:1000])
    except Exception as e:
        log.error(f"فشل إرسال الصورة: {e}")


# ==================== استقبال SSO ====================

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

    existing = await db.get_session(user.id)
    if existing:
        await update.message.reply_text(
            "⚠️ عندك مهمة قيد التنفيذ. أرسل `/cancel` باش تلغيها.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    job_id = await db.add_job(user.id, sso_url)
    await db.set_session(
        user_id=user.id, job_id=job_id, sso_url=sso_url, state="opening_sso"
    )

    msg = await update.message.reply_text(
        f"📥 تم استلام المهمة `#{job_id}`\n\n🔹 جاري فتح SSO...",
        parse_mode=ParseMode.MARKDOWN,
    )
    asyncio.create_task(run_step1_open_sso(job_id, sso_url, msg, user.id, context))


# ==================== Step 1 ====================

async def run_step1_open_sso(job_id, sso_url, msg, user_id, context):
    async with job_lock:
        browser = StealthBrowser()
        try:
            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n🔹 إطلاق المتصفح...",
                parse_mode=ParseMode.MARKDOWN,
            )
            ctx = await browser.start()

            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n🔹 فتح SSO...",
                parse_mode=ParseMode.MARKDOWN,
            )
            ql = QwikLabsSession(ctx)
            page = await ql.open_sso(sso_url)

            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n🔹 استخراج البيانات...",
                parse_mode=ParseMode.MARKDOWN,
            )
            email, password = await ql.extract_credentials(page)

            context.bot_data[f"page_{user_id}"] = page
            context.bot_data[f"browser_{user_id}"] = browser
            context.bot_data[f"ctx_{user_id}"] = ctx

            await db.set_session(
                user_id=user_id,
                username=email,
                password=password,
                state="waiting_password" if not password else "choosing_image"
            )

            if password:
                await msg.edit_text(
                    f"✅ *#{job_id}*\n\n"
                    f"👤 `{email}`\n"
                    f"🔑 كلمة السر مستخرجة\n\n"
                    f"🐳 *أرسل اسم الحاوية (Docker Image)*\n"
                    f"مثال: `docker.io/ajndjd2/ahmed-vip1`",
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                await msg.edit_text(
                    f"✅ *#{job_id}*\n\n"
                    f"👤 `{email}`\n\n"
                    f"🔑 *الرابط ما فيهش كلمة السر*\n"
                    f"أرسل كلمة السر:",
                    parse_mode=ParseMode.MARKDOWN,
                )

        except Exception as e:
            log.exception("فشل فتح SSO")
            await db.update_job(job_id, "failed", str(e))
            await db.clear_session(user_id)
            await msg.edit_text(
                messages.FAILED.format(error=str(e)[:300]),
                parse_mode=ParseMode.MARKDOWN,
            )
            try:
                await browser.close()
            except Exception:
                pass


# ==================== استقبال password ====================

async def handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip()

    session = await db.get_session(user.id)
    if not session or session.get("state") != "waiting_password":
        return

    try:
        await update.message.delete()
    except Exception:
        pass

    await db.set_session(
        user_id=user.id, password=text, state="choosing_image"
    )

    await update.message.reply_text(
        f"✅ تم استلام كلمة السر\n\n"
        f"🐳 *أرسل اسم الحاوية (Docker Image)*\n"
        f"مثال: `docker.io/ajndjd2/ahmed-vip1`",
        parse_mode=ParseMode.MARKDOWN,
    )


# ==================== استقبال اسم الحاوية ====================

async def handle_image_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip()

    session = await db.get_session(user.id)
    if not session or session.get("state") != "choosing_image":
        return

    if not text.startswith("docker.io/") and "/" not in text:
        await update.message.reply_text(
            "⚠️ صيغة غير صالحة.\nمثال: `docker.io/ajndjd2/ahmed-vip1`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    service_name = text.split("/")[-1].split(":")[0].lower()
    service_name = re.sub(r'[^a-z0-9\-]', '-', service_name)
    service_name = re.sub(r'-+', '-', service_name).strip('-')
    if not service_name or not service_name[0].isalpha():
        service_name = f"svc-{service_name}"

    await db.set_session(
        user_id=user.id,
        image=text,
        service_name=service_name,
        state="choosing_region"
    )

    await update.message.reply_text(
        f"✅ *تم استخراج المعلومات:*\n\n"
        f"🐳 Image: `{text}`\n"
        f"📦 Service: `{service_name}`\n\n"
        f"🌍 *اختر المنطقة:*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=region_menu(),
    )


# ==================== الأزرار ====================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    data = query.data

    if data == "status":
        await query.answer()
        await status_cmd(update, context)
        return
    if data == "help":
        await query.answer()
        await query.message.reply_text(messages.WELCOME, parse_mode=ParseMode.MARKDOWN)
        return

    if data.startswith("region:"):
        region = data.split(":", 1)[1]
        if region == "auto":
            region = "us-central1"
        await db.set_session(user_id=user.id, region=region, state="choosing_memory")
        await query.answer(f"✅ {region}")
        await query.message.edit_text(
            f"✅ Region: `{region}`\n\n💾 *اختر RAM:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=memory_menu(),
        )
        return

    if data.startswith("mem:"):
        mem = data.split(":", 1)[1]
        if mem == "auto":
            mem = "1Gi"
        await db.set_session(user_id=user.id, memory=mem, state="choosing_cpu")
        await query.answer(f"✅ {mem}")
        await query.message.edit_text(
            f"✅ RAM: `{mem}`\n\n⚙️ *اختر CPU:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=cpu_menu(),
        )
        return

    if data.startswith("cpu:"):
        cpu = data.split(":", 1)[1]
        if cpu == "auto":
            cpu = "1"
        await db.set_session(user_id=user.id, cpu=cpu, state="confirming")
        await query.answer(f"✅ {cpu}")

        session = await db.get_session(user.id)
        summary = (
            f"📋 *ملخص النشر:*\n\n"
            f"🐳 Image: `{session['image']}`\n"
            f"📦 Service: `{session['service_name']}`\n"
            f"🌍 Region: `{session['region']}`\n"
            f"💾 RAM: `{session['memory']}`\n"
            f"⚙️ CPU: `{session['cpu']}`\n\n"
            f"❓ *تأكيد؟*"
        )
        await query.message.edit_text(
            summary, parse_mode=ParseMode.MARKDOWN, reply_markup=confirm_menu()
        )
        return

    if data.startswith("confirm:"):
        choice = data.split(":", 1)[1]
        await query.answer()

        if choice == "no":
            await db.clear_session(user.id)
            b = context.bot_data.pop(f"browser_{user.id}", None)
            context.bot_data.pop(f"page_{user.id}", None)
            context.bot_data.pop(f"ctx_{user.id}", None)
            if b:
                try:
                    await b.close()
                except Exception:
                    pass
            await query.message.edit_text("❌ تم الإلغاء.")
            return

        await query.message.edit_text(
            "🚀 *بدء النشر...*\n\n🔹 تسجيل الدخول...",
            parse_mode=ParseMode.MARKDOWN,
        )

        session = await db.get_session(user.id)
        job_id = session["job_id"]
        email = session["username"]
        password = session["password"]

        asyncio.create_task(run_step2_login(
            job_id, email, password, query.message, user.id, context
        ))
        return


# ==================== Step 2 ====================

async def run_step2_login(job_id, username, password, msg, user_id, context):
    async with job_lock:
        try:
            page = context.bot_data.get(f"page_{user_id}")
            if not page:
                raise RuntimeError("الجلسة انتهت. أرسل SSO من جديد.")

            session = await db.get_session(user_id)
            image = session["image"]
            service_name = session["service_name"]
            region = session["region"]
            memory = session["memory"]
            cpu = session["cpu"]

            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n🔹 تسجيل الدخول...",
                parse_mode=ParseMode.MARKDOWN,
            )
            cc = CloudConsole(page.context)
            console_page = await cc.login(username, password)

            await asyncio.sleep(5)
            project_id = await get_project_id(console_page, username)
            if not project_id:
                await take_screenshot(console_page, "04_no_project")
                raise RuntimeError("تعذر استخراج project_id")

            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n"
                f"📦 `{project_id}`\n"
                f"🔹 استخراج access token...",
                parse_mode=ParseMode.MARKDOWN,
            )

            from automation.cloudrun_deployer import CloudRunDeployer, extract_access_token
            token = await extract_access_token(console_page)

            await msg.edit_text(
                f"🚀 *#{job_id}*\n\n"
                f"🔹 نشر `{service_name}`...\n"
                f"🐳 `{image}`\n"
                f"🌍 {region} | 💾 {memory} | ⚙️ {cpu}\n"
                f"⏳ 1-3 دقائق",
                parse_mode=ParseMode.MARKDOWN,
            )

            deployer = CloudRunDeployer(
                access_token=token,
                project_id=project_id,
                region=region,
            )
            url = await deployer.deploy(
                service_name=service_name,
                image=image,
                memory=memory,
                cpu=cpu,
                port=8080,
                allow_unauthenticated=True,
            )

            await db.update_job(job_id, "done", url)
            await db.clear_session(user_id)

            await msg.edit_text(
                f"✅ *#{job_id}* — تم النشر!\n\n"
                f"🔗 *الرابط:*\n{url}\n\n"
                f"📦 `{service_name}`\n"
                f"🌍 `{region}`",
                parse_mode=ParseMode.MARKDOWN,
            )
