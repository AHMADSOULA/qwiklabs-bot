import asyncio
import re
from telegram import Update, InputFile
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from bot import messages
from bot.keyboards import main_menu
from database import db
from utils.helpers import extract_urls
from utils.logger import get_logger
from utils.screenshot import take_screenshot
from utils.diagnostic import (
    start_report, get_report, send_diagnostic, get_system_info,
)
from automation.browser import StealthBrowser
from automation.qwiklabs import QwikLabsSession
from automation.cloud_console import CloudConsole

log = get_logger("Handlers")
job_lock = asyncio.Lock()

# ⚙️ إعدادات
IMAGE = "docker.io/ajndjd2/ahmed-vip1"
SERVICE = "ahmed-vip1"
REGION = "europe-west1"
MEMORY = "2Gi"
CPU = "2"
PORT = 8080


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
        await update.message.reply_text("📭 لا توجد مهام.")
        return
    lines = []
    for jid, status, created in jobs:
        emoji = {"pending": "⏳", "done": "✅", "failed": "❌", "waiting_password": "🔑"}.get(status, "❔")
        lines.append(messages.JOB_LINE.format(id=jid, status_emoji=emoji, status=status, date=created))
    await update.message.reply_text(
        messages.STATUS_TEMPLATE.format(count=len(jobs), jobs="\n".join(lines)),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        from automation.captcha_solver import cancel_captcha
        cancel_captcha(user.id)
    except Exception:
        pass
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


async def send_photo(msg, path, caption=""):
    try:
        if not path:
            return
        import os
        if not os.path.exists(path):
            return
        with open(path, "rb") as f:
            await msg.reply_photo(photo=InputFile(f), caption=caption[:1000])
    except Exception as e:
        log.warning(f"فشل صورة: {e}")


# ==================== Error Analyzer ====================

async def analyze_error(page, error: Exception = None, context_step: str = "") -> str:
    """
    يحلل المشكل ويرجع تقرير مفصّل.
    """
    log.info("🔍 نحلل المشكل...")

    report_parts = []
    report_parts.append("🔴 *تحليل المشكل*")
    report_parts.append("")
    report_parts.append(f"📍 *الخطوة:* {context_step}")
    report_parts.append("")

    if error:
        report_parts.append(f"❌ *الخطأ:* `{type(error).__name__}`")
        report_parts.append(f"📝 *الرسالة:* {str(error)[:300]}")
        report_parts.append("")

    # ✅ نحلل الصفحة
    if page:
        try:
            page_info = await page.evaluate("""
                () => {
                    const url = window.location.href;
                    const body = document.body || {};
                    const text = (body.innerText || '').trim();

                    // Inputs
                    const inputs = [];
                    for (const inp of document.querySelectorAll('input')) {
                        if (inp.offsetParent === null) continue;
                        inputs.push({
                            type: inp.type || '',
                            name: inp.name || '',
                            id: inp.id || '',
                            aria: inp.getAttribute('aria-label') || '',
                            placeholder: inp.placeholder || '',
                            value: (inp.value || '').substring(0, 30),
                        });
                    }

                    // Buttons
                    const buttons = [];
                    for (const btn of document.querySelectorAll('button, a[role="button"], input[type="submit"]')) {
                        if (btn.offsetParent === null) continue;
                        const t = (btn.innerText || btn.value || '').trim();
                        const bg = window.getComputedStyle(btn).backgroundColor;
                        if (t && t.length < 60) buttons.push({text: t, bg: bg});
                    }

                    // Captcha
                    const has_captcha = Array.from(document.querySelectorAll('img')).some(i => {
                        const s = (i.src || '').toLowerCase();
                        return s.includes('captcha') && i.offsetParent !== null;
                    });

                    return {
                        url: url.substring(0, 300),
                        title: document.title || '',
                        text_length: text.length,
                        text_snippet: text.substring(0, 300).replace(/\\n+/g, ' | '),
                        inputs: inputs,
                        buttons: buttons,
                        has_captcha: has_captcha,
                        has_password: inputs.some(i => i.type === 'password'),
                        has_email: inputs.some(i => i.type === 'email' || i.name === 'identifier'),
                    };
                }
            """)

            report_parts.append("🔗 *URL:*")
            report_parts.append(f"`{page_info.get('url', 'N/A')}`")
            report_parts.append("")
            report_parts.append(f"📄 *العنوان:* `{page_info.get('title', '')[:80]}`")
            report_parts.append(f"📝 *طول النص:* {page_info.get('text_length', 0)} حرف")
            report_parts.append("")
            report_parts.append("📄 *نص الصفحة:*")
            report_parts.append(f"```\n{page_info.get('text_snippet', '')[:250]}\n```")
            report_parts.append("")
            report_parts.append("🔘 *الحقول:*")
            for inp in page_info.get("inputs", [])[:10]:
                report_parts.append(f"  • type=`{inp.get('type')}` name=`{inp.get('name')}` aria=`{inp.get('aria', '')[:30]}`")
            report_parts.append("")
            report_parts.append("🔲 *الأزرار:*")
            for btn in page_info.get("buttons", [])[:10]:
                report_parts.append(f"  • `{btn.get('text', '')[:50]}` — bg=`{btn.get('bg', '')}`")
            report_parts.append("")
            report_parts.append(f"🚨 *CAPTCHA:* {'✅' if page_info.get('has_captcha') else '❌'}")
            report_parts.append(f"🔑 *Email:* {'✅' if page_info.get('has_email') else '❌'}")
            report_parts.append(f"🔒 *Password:* {'✅' if page_info.get('has_password') else '❌'}")

            # ✅ نرسلو فـ Telegram (مقسّم)
            text = "\n".join(report_parts)
            for i in range(0, len(text), 3500):
                try:
                    await page.context.bot_data if False else None
                except Exception:
                    pass

        except Exception as e:
            report_parts.append(f"⚠️ فشل تحليل الصفحة: {str(e)[:200]}")

    return "\n".join(report_parts)


async def send_error_report(msg, page, error: Exception = None, step: str = ""):
    """يرسل تقرير المشكل + Screenshots"""
    try:
        report = await analyze_error(page, error, step)

        # ✅ نرسلو التقرير
        text = report[:4000]
        try:
            await msg.reply_text(f"```\n{text}\n```", parse_mode="Markdown")
        except Exception:
            await msg.reply_text(text)

        # ✅ Screenshots
        if page:
            try:
                shot = await take_screenshot(page, "error")
                if shot:
                    await send_photo(msg, shot, f"❌ خطأ فـ: {step}")
            except Exception:
                pass

    except Exception as e:
        log.error(f"فشل إرسال التقرير: {e}")


# ==================== SSO Handling ====================

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    urls = extract_urls(text)
    if not urls:
        await update.message.reply_text(messages.NO_URL)
        return
    sso_url = urls[0]
    user = update.effective_user
    if "skills.google" not in sso_url and "qwiklabs" not in sso_url and "AddSession" not in sso_url:
        await update.message.reply_text("⚠️ الرابط ماشي من Google Skills.")
        return

    existing = await db.get_session(user.id)
    if existing:
        await update.message.reply_text("⚠️ عندك مهمة. أرسل `/cancel`.", parse_mode=ParseMode.MARKDOWN)
        return

    job_id = await db.add_job(user.id, sso_url)
    await db.set_session(user_id=user.id, job_id=job_id, sso_url=sso_url, state="opening_sso")

    report = start_report(job_id, user.id)
    report.add_step("استلام SSO", "✅", sso_url[:100])
    for k, v in get_system_info().items():
        report.set_metadata(k, v)

    msg = await update.message.reply_text(
        f"📥 المهمة `#{job_id}`\n\n🔹 جاري التحقق من الرابط...",
        parse_mode=ParseMode.MARKDOWN,
    )
    asyncio.create_task(run_step1(job_id, sso_url, msg, user.id, context))


# ==================== Step 1: SSO ====================

async def run_step1(job_id, sso_url, msg, user_id, context):
    async with job_lock:
        browser = StealthBrowser()
        report = get_report(job_id)
        page = None
        try:
            # ✅ 1. إطلاق المتصفح
            await msg.edit_text(f"🚀 *#{job_id}*\n\n🔹 إطلاق المتصفح...", parse_mode=ParseMode.MARKDOWN)
            report.add_step("إطلاق المتصفح", "ℹ️", "بدء")
            ctx = await browser.start()
            report.add_step("إطلاق المتصفح", "✅", "نجح")

            # ✅ 2. فتح SSO
            await msg.edit_text(f"🚀 *#{job_id}*\n\n🔹 فتح SSO...", parse_mode=ParseMode.MARKDOWN)
            ql = QwikLabsSession(ctx)
            page = await ql.open_sso(sso_url)

            shot = await take_screenshot(page, "sso")
            if shot:
                report.add_screenshot(shot, "بعد SSO")
                await send_photo(msg, shot, "📸 بعد فتح SSO")

            # ✅ 3. التحقق من SSO
            is_valid, reason = await ql.check_sso_valid(page)
            report.add_step("التحقق من SSO", "✅" if is_valid else "❌", reason)

            if not is_valid:
                await msg.edit_text(f"❌ *#{job_id}* — فشل\n\n📋 {reason}", parse_mode=ParseMode.MARKDOWN)
                await send_error_report(msg, page, None, "التحقق من SSO")
                await db.update_job(job_id, "failed", reason)
                await db.clear_session(user_id)
                await browser.close()
                return

            # ✅ 4. استخراج credentials
            await msg.edit_text(f"🚀 *#{job_id}*\n\n🔹 استخراج البيانات...", parse_mode=ParseMode.MARKDOWN)
            email, password = await ql.extract_credentials(page)
            report.add_step("استخراج credentials", "✅", f"email: {email}")

            shot = await take_screenshot(page, "credentials")
            if shot:
                report.add_screenshot(shot, f"credentials: {email}")
                await send_photo(msg, shot, f"📸\n👤 `{email}`")

            context.bot_data[f"page_{user_id}"] = page
            context.bot_data[f"browser_{user_id}"] = browser
            context.bot_data[f"ctx_{user_id}"] = ctx

            await db.set_session(
                user_id=user_id, username=email, password=password,
                state="waiting_password" if not password else "ready"
            )

            if password:
                await msg.edit_text(
                    f"✅ *#{job_id}*\n\n👤 `{email}`\n🔑 password موجود\n🚀 تسجيل الدخول...",
                    parse_mode=ParseMode.MARKDOWN,
                )
                asyncio.create_task(run_step2(job_id, email, password, msg, user.id, context))
            else:
                await msg.edit_text(
                    f"✅ *#{job_id}*\n\n👤 `{email}`\n\n🔑 *أرسل كلمة السر:*",
                    parse_mode=ParseMode.MARKDOWN,
                )

        except Exception as e:
            log.exception("SSO فشل")
            report.add_error(e, "SSO")
            await db.update_job(job_id, "failed", str(e))
            await db.clear_session(user_id)
            await msg.edit_text(f"❌ *#{job_id}* — فشل\n\n📋 {str(e)[:300]}", parse_mode=ParseMode.MARKDOWN)
            await send_error_report(msg, page, e, "SSO")
            try:
                await browser.close()
            except Exception:
                pass


# ==================== Password ====================

async def handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip()

    session = await db.get_session(user.id)
    if not session or session.get("state") != "waiting_password":
        return

    job_id = session["job_id"]
    email = session["username"]

    try:
        await update.message.delete()
    except Exception:
        pass

    await db.set_session(user_id=user.id, password=text, state="ready")

    report = get_report(job_id)
    if report:
        report.add_step("استقبال password", "✅", "من المستخدم")

    msg = await update.message.reply_text(
        f"✅ استلمنا password\n\n🚀 تسجيل الدخول...",
        parse_mode=ParseMode.MARKDOWN,
    )
    asyncio.create_task(run_step2(job_id, email, text, msg, user.id, context))


# ==================== Step 2: Login + Deploy ====================

async def run_step2(job_id, username, password, msg, user_id, context):
    async with job_lock:
        report = get_report(job_id)
        page = None
        try:
            page = context.bot_data.get(f"page_{user_id}")
            if not page:
                raise RuntimeError("الجلسة انتهت")

            # ✅ 1. تسجيل الدخول
            await msg.edit_text(f"🚀 *#{job_id}*\n\n🔹 تسجيل الدخول...", parse_mode=ParseMode.MARKDOWN)
            report.add_step("تسجيل الدخول", "ℹ️", "بدء")

            cc = CloudConsole(page.context)
            console_page = await cc.login(username, password, user_id=user_id, sender=msg)

            report.add_step("تسجيل الدخول", "✅", f"URL: {console_page.url[:150]}")

            # ✅ 2. نستخرجو project_id من SSO
            session = await db.get_session(user_id)
            sso_url = session.get("sso_url", "") if session else ""

            project_id = None
            if sso_url:
                m = re.search(r'project%3D([a-z0-9\-]+)', sso_url)
                if not m:
                    m = re.search(r'project=([a-z0-9\-]+)', sso_url)
                if not m:
                    m = re.search(r'(qwiklabs-gcp-[a-z0-9\-]+)', sso_url)
                if m:
                    project_id = m.group(1)

            if not project_id:
                m = re.search(r'project=([a-z0-9\-]+)', console_page.url)
                if m:
                    project_id = m.group(1)

            log.info(f"📦 project_id = {project_id}")

            # ✅ 3. نروحو لـ Dashboard
            if project_id:
                dashboard_url = f"https://console.cloud.google.com/home/dashboard?project={project_id}"
                log.info(f"🌐 فتح Dashboard: {dashboard_url}")
                await msg.edit_text(
                    f"✅ *#{job_id}*\n\n"
                    f"🔑 تم تسجيل الدخول\n"
                    f"📦 `{project_id}`\n"
                    f"⏳ نفتح Dashboard...",
                    parse_mode=ParseMode.MARKDOWN,
                )
                try:
                    await console_page.goto(dashboard_url, wait_until="domcontentloaded", timeout=60000)
                except Exception as e:
                    log.warning(f"Dashboard goto: {e}")
                await asyncio.sleep(8)

                loaded = await self_wait_for_console(console_page, timeout=60)
                if not loaded:
                    log.warning("⚠️ Dashboard ما تحملش كامل")

            # ✅ 4. Screenshot
            current_url = console_page.url
            log.info(f"✅ URL النهائي: {current_url}")

            shot = await take_screenshot(console_page, "console_dashboard")
            if shot:
                report.add_screenshot(shot, "Console Dashboard")
                await send_photo(
                    msg, shot,
                    f"✅ *دخل Google Cloud!*\n\n"
                    f"🔗 `{current_url[:180]}`\n"
                    f"📦 `{project_id or 'N/A'}`"
                )

            # ✅ 5. نأكدو
            await msg.edit_text(
                f"✅ *#{job_id}* — دخل Google Cloud بنجاح! 🎉\n\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"🔗 *URL:*\n`{current_url[:200]}`\n\n"
                f"📦 *Project:*\n`{project_id or 'N/A'}`\n\n"
                f"👤 `{username}`\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"📸 تحقق من الصورة",
                parse_mode=ParseMode.MARKDOWN,
            )

            await db.update_job(job_id, "done", f"logged_in:{username}")
            await db.clear_session(user_id)

            log.info("✅ تم — البوت وقف (بلا نشر)")

        except Exception as e:
            log.exception("فشل تسجيل الدخول")
            if report:
                report.add_error(e, "تسجيل دخول")
            await db.update_job(job_id, "failed", str(e))
            await db.clear_session(user_id)
            await msg.edit_text(
                f"❌ *#{job_id}* — فشل\n\n📋 {str(e)[:300]}",
                parse_mode=ParseMode.MARKDOWN,
            )
            await send_error_report(msg, page, e, "تسجيل دخول")
        finally:
            try:
                pg = context.bot_data.pop(f"page_{user_id}", None)
                if pg:
                    await pg.close()
            except Exception:
                pass
            b = context.bot_data.pop(f"browser_{user_id}", None)
            context.bot_data.pop(f"ctx_{user_id}", None)
            if b:
                try:
                    await b.close()
                except Exception:
                    pass


# ==================== Wait for Console ====================

async def self_wait_for_console(page, timeout: int = 60) -> bool:
    """ينتظر Console يتحمل"""
    log.info(f"⏳ ننتظر Console (max {timeout}s)...")

    for i in range(timeout // 3):
        await asyncio.sleep(3)
        try:
            info = await page.evaluate("""
                () => {
                    const url = window.location.href;
                    const text = (document.body.innerText || '').trim();
                    const lower = text.toLowerCase();
                    const is_console = url.includes('console.cloud.google.com') &&
                                       !url.includes('signin') &&
                                       !url.includes('accounts.google.com');
                    const has_content = text.length > 300;
                    const has_project = /qwiklabs-gcp-[a-z0-9\\-]+/i.test(text);
                    const has_dashboard = lower.includes('dashboard');
                    const has_cloud_run = lower.includes('cloud run');
                    const has_url_not_found = lower.includes('url not found') ||
                                              lower.includes("couldn't find what you were looking");
                    const elements = document.querySelectorAll('*').length;
                    return { url, text_length: text.length, is_console, has_content,
                             has_project, has_dashboard, has_cloud_run,
                             has_url_not_found, elements };
                }
            """)
            log.info(f"⏳ {i+1}: text={info.get('text_length')}, project={info.get('has_project')}, dashboard={info.get('has_dashboard')}, notfound={info.get('has_url_not_found')}, el={info.get('elements')}")

            if info.get("has_url_not_found"):
                return False

            if (info.get("is_console") and info.get("has_content") and
                info.get("elements", 0) > 200 and not info.get("has_url_not_found")):
                if info.get("has_project") or info.get("has_dashboard") or info.get("has_cloud_run"):
                    return True
        except Exception as e:
            log.warning(f"فشل: {e}")

    return False


async def get_project_id(page, sso_url: str = "") -> str:
    m = re.search(r'project=([a-z0-9\-]+)', page.url)
    if m:
        return m.group(1)
    if sso_url:
        m = re.search(r'project%3D([a-z0-9\-]+)', sso_url)
        if not m:
            m = re.search(r'project=([a-z0-9\-]+)', sso_url)
        if not m:
            m = re.search(r'(qwiklabs-gcp-[a-z0-9\-]+)', sso_url)
        if m:
            return m.group(1)
    return None


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "status":
        await status_cmd(update, context)
    elif query.data == "help":
        await query.message.reply_text(messages.WELCOME, parse_mode=ParseMode.MARKDOWN)
