"""
AI Debugger — نظام تشخيص ذكي
- يلقط كل خطوة
- يحلل الصفحة (inputs, buttons, errors)
- يكتشف المشاكل تلقائياً
- يرسل تقرير كامل لـ Telegram
"""
import os
import time
import traceback
from datetime import datetime
from utils.logger import get_logger

log = get_logger("Diagnostic")

DIAG_DIR = "/app/data/diagnostics"
os.makedirs(DIAG_DIR, exist_ok=True)


class DiagnosticReport:
    def __init__(self, job_id: int = None, user_id: int = None):
        self.job_id = job_id
        self.user_id = user_id
        self.start_time = time.time()
        self.steps = []
        self.errors = []
        self.screenshots = []
        self.metadata = {}
        self.analysis = None
        self.diagnosis = None

    def add_step(self, name: str, status: str, details: str = ""):
        elapsed = round(time.time() - self.start_time, 2)
        self.steps.append({
            "time": f"+{elapsed}s",
            "name": name,
            "status": status,
            "details": details[:500] if details else "",
        })
        log.info(f"[{status}] {name}: {details[:100]}")

    def add_error(self, error: Exception, context: str = ""):
        tb = traceback.format_exc()
        self.errors.append({
            "context": context,
            "type": type(error).__name__,
            "message": str(error)[:500],
            "traceback": tb[-2000:],
        })
        log.error(f"❌ {context}: {error}")

    def add_screenshot(self, path: str, caption: str = ""):
        if path and os.path.exists(path):
            self.screenshots.append({"path": path, "caption": caption[:200]})

    def add_analysis(self, analysis: dict):
        self.analysis = analysis

    def add_diagnosis(self, diagnosis: str):
        self.diagnosis = diagnosis

    def set_metadata(self, key: str, value):
        self.metadata[key] = value

    def build_report(self) -> str:
        lines = []
        lines.append("═" * 50)
        lines.append("📊 تقرير التشخيص")
        lines.append("═" * 50)
        lines.append("")
        lines.append(f"🆔 Job: #{self.job_id} | 👤 User: {self.user_id}")
        lines.append(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"⏱️ المدة: {round(time.time() - self.start_time, 2)}s")
        lines.append("")

        if self.metadata:
            lines.append("📋 النظام:")
            for k, v in self.metadata.items():
                lines.append(f"  • {k}: {v}")
            lines.append("")

        if self.steps:
            lines.append("📝 الخطوات:")
            for s in self.steps:
                lines.append(f"  [{s['time']}] {s['status']} {s['name']}")
                if s['details']:
                    lines.append(f"      → {s['details']}")
            lines.append("")

        if self.diagnosis:
            lines.append("🧠 التشخيص الذكي:")
            lines.append(f"  {self.diagnosis}")
            lines.append("")

        if self.analysis:
            lines.append("🔍 تحليل الصفحة:")
            for k, v in self.analysis.items():
                lines.append(f"  • {k}: {v}")
            lines.append("")

        if self.errors:
            lines.append("❌ الأخطاء:")
            for i, e in enumerate(self.errors, 1):
                lines.append(f"  [{i}] {e['context']}")
                lines.append(f"      Type: {e['type']}")
                lines.append(f"      Msg: {e['message']}")
            lines.append("")

        if self.screenshots:
            lines.append(f"📸 Screenshots: {len(self.screenshots)}")
            for s in self.screenshots:
                lines.append(f"  • {s['caption']}")
            lines.append("")

        lines.append("═" * 50)
        return "\n".join(lines)

    def save(self) -> str:
        report_text = self.build_report()
        filepath = f"{DIAG_DIR}/job_{self.job_id}_{int(time.time())}.txt"
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(report_text)
        except Exception:
            pass
        return filepath


PENDING_REPORTS = {}


def start_report(job_id: int, user_id: int) -> DiagnosticReport:
    report = DiagnosticReport(job_id=job_id, user_id=user_id)
    PENDING_REPORTS[job_id] = report
    return report


def get_report(job_id: int) -> DiagnosticReport:
    return PENDING_REPORTS.get(job_id)


def end_report(job_id: int) -> str:
    report = PENDING_REPORTS.pop(job_id, None)
    if not report:
        return "ما كاينش تقرير"
    report.save()
    return report.build_report()


# ==================== AI Analysis ====================

async def analyze_page(page) -> dict:
    """يحلل الصفحة — inputs, buttons, text, errors"""
    try:
        return await page.evaluate("""
            () => {
                const r = {
                    url: window.location.href.substring(0, 200),
                    title: document.title || '',
                    bodyText: (document.body.innerText || '').substring(0, 300).replace(/\\n/g, ' | '),
                    inputs: [],
                    buttons: [],
                    hasCaptcha: false,
                    hasPassword: false,
                    hasEmail: false,
                    hasAccept: false,
                    hasWelcome: false,
                    hasVerify: false,
                    hasError: false,
                    errorText: '',
                };
                for (const inp of document.querySelectorAll('input')) {
                    if (inp.offsetParent === null) continue;
                    r.inputs.push({
                        type: inp.type || '',
                        name: inp.name || '',
                        id: inp.id || '',
                        placeholder: inp.placeholder || '',
                        value: (inp.value || '').substring(0, 30),
                    });
                    if (inp.type === 'password') r.hasPassword = true;
                    if (inp.type === 'email' || inp.name === 'identifier') r.hasEmail = true;
                }
                for (const btn of document.querySelectorAll('button, a[role="button"]')) {
                    if (btn.offsetParent === null) continue;
                    const t = (btn.innerText || btn.value || '').trim();
                    if (t.length > 0 && t.length < 80) {
                        r.buttons.push(t.substring(0, 50));
                        const tl = t.toLowerCase();
                        if (tl.includes('accept') || tl.includes('understand') || tl.includes('agree')) r.hasAccept = true;
                    }
                }
                for (const img of document.querySelectorAll('img')) {
                    const s = (img.src || '').toLowerCase();
                    if (s.includes('captcha')) r.hasCaptcha = true;
                }
                const bt = (document.body.innerText || '').toLowerCase();
                if (bt.includes('welcome to your new account')) r.hasWelcome = true;
                if (bt.includes('verify it') || bt.includes('2-step') || bt.includes('enter the code')) r.hasVerify = true;
                if (bt.includes('incorrect password') || bt.includes('wrong password')) {
                    r.hasError = true;
                    r.errorText = 'كلمة السر غلط';
                }
                if (bt.includes('couldn\\'t sign you in') || bt.includes('browser or app may not be secure')) {
                    r.hasError = true;
                    r.errorText = 'Google حظرت المتصفح';
                }
                return r;
            }
        """)
    except Exception as e:
        return {"error": str(e)}


def diagnose(analysis: dict, error: str = "") -> str:
    """تشخيص ذكي — يقترح الحل"""
    if not analysis:
        return "ما قدرتش نحلل الصفحة"

    url = analysis.get("url", "").lower()
    error_lower = (error or "").lower()

    # ✅ تشخيصات
    if "couldn't sign you in" in analysis.get("bodyText", "").lower() or \
       "browser or app may not be secure" in analysis.get("bodyText", "").lower():
        return "🔴 Google حظرت المتصفح — الحل: VPS + Proxy residential"

    if analysis.get("hasError"):
        return f"🔴 {analysis.get('errorText', 'خطأ')}"

    if analysis.get("hasVerify"):
        return "🔴 Google كتطلب verify (2FA) — الحل: تسجيل يدوي"

    if analysis.get("hasCaptcha"):
        return "🟡 CAPTCHA موجودة — البوت كيحلها (manual/truecaptcha)"

    if "workspacetermsofservice" in url or "speedbump" in url:
        if analysis.get("hasAccept"):
            return "🟡 صفحة TOS/Speedbump — نضغط Accept"
        return "🔴 صفحة TOS/Speedbump — ما لقيتش زر Accept"

    if analysis.get("hasWelcome") and analysis.get("hasAccept"):
        return "🟢 صفحة Welcome — نضغط Accept"

    if analysis.get("hasPassword"):
        return "🟢 حقل password موجود — نكمل"

    if analysis.get("hasEmail"):
        return "🟢 حقل email موجود — نكتب email"

    if "accounts.google.com" in url:
        return "🟡 فـ Sign in — مازال"

    if "console.cloud.google.com" in url and "signin" not in url:
        return "🟢 وصلنا للـ Console"

    return f"🟡 حالة غير معروفة: {url[:100]}"


async def send_diagnostic(sender, job_id: int, error_msg: str = ""):
    """يرسل التقرير للمستخدم"""
    report = get_report(job_id)
    if not report:
        await sender.reply_text(f"❌ خطأ:\n\n{error_msg[:3000]}")
        return

    report_text = report.build_report()
    max_len = 3500

    if len(report_text) > max_len:
        parts = [report_text[i:i+max_len] for i in range(0, len(report_text), max_len)]
        for i, part in enumerate(parts):
            try:
                await sender.reply_text(f"📊 ({i+1}/{len(parts)}):\n\n```\n{part}\n```", parse_mode="Markdown")
            except Exception:
                await sender.reply_text(f"📊 ({i+1}/{len(parts)}):\n\n{part[:3000]}")
    else:
        try:
            await sender.reply_text(f"📊 التقرير:\n\n```\n{report_text}\n```", parse_mode="Markdown")
        except Exception:
            await sender.reply_text(f"📊 التقرير:\n\n{report_text[:3000]}")

    for shot in report.screenshots[-5:]:
        try:
            from telegram import InputFile
            with open(shot["path"], "rb") as f:
                await sender.reply_photo(photo=InputFile(f), caption=f"📸 {shot['caption'][:200]}")
        except Exception:
            pass


def get_system_info() -> dict:
    from config import config
    return {
        "CAPTCHA_MODE": config.CAPTCHA_MODE,
        "HEADLESS": config.HEADLESS,
        "PROXY": "✅" if config.PROXY_ENABLED else "❌",
        "TrueCaptcha": "✅" if config.CAPTCHA_APIKEY else "❌",
    }
