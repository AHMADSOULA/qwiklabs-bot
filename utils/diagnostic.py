"""
نظام التشخيص — يسجل كل الأخطاء والمعلومات
"""
import os
import time
import json
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
            self.screenshots.append({
                "path": path,
                "caption": caption[:200],
            })

    def set_metadata(self, key: str, value):
        self.metadata[key] = value

    def build_report(self) -> str:
        lines = []
        lines.append("=" * 50)
        lines.append("📊 تقرير التشخيص")
        lines.append("=" * 50)
        lines.append("")
        lines.append(f"🆔 Job ID: {self.job_id}")
        lines.append(f"👤 User ID: {self.user_id}")
        lines.append(f"⏰ الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"⏱️ المدة: {round(time.time() - self.start_time, 2)}s")
        lines.append("")

        if self.metadata:
            lines.append("📋 معلومات النظام:")
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

        if self.errors:
            lines.append("❌ الأخطاء:")
            for i, e in enumerate(self.errors, 1):
                lines.append(f"  [{i}] {e['context']}")
                lines.append(f"      Type: {e['type']}")
                lines.append(f"      Message: {e['message']}")
                if e['traceback']:
                    lines.append(f"      Traceback:")
                    for tb_line in e['traceback'].split('\n')[-10:]:
                        lines.append(f"        {tb_line}")
                lines.append("")

        if self.screenshots:
            lines.append(f"📸 Screenshots: {len(self.screenshots)}")
            for s in self.screenshots:
                lines.append(f"  • {s['caption']} → {s['path']}")
            lines.append("")

        lines.append("=" * 50)
        return "\n".join(lines)

    def save(self) -> str:
        report_text = self.build_report()
        filepath = f"{DIAG_DIR}/job_{self.job_id}_{int(time.time())}.txt"
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(report_text)
            log.info(f"💾 التقرير محفوظ: {filepath}")
        except Exception as e:
            log.error(f"فشل حفظ التقرير: {e}")
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


async def send_diagnostic(sender, job_id: int, error_msg: str = ""):
    report = get_report(job_id)
    if not report:
        await sender.reply_text(
            f"❌ *خطأ:*\n\n{error_msg[:3000]}\n\n⚠️ ما كاينش تقرير.",
            parse_mode="Markdown",
        )
        return

    report_text = report.build_report()
    max_len = 4000

    if len(report_text) > max_len:
        parts = [report_text[i:i+max_len] for i in range(0, len(report_text), max_len)]
        for i, part in enumerate(parts):
            await sender.reply_text(
                f"📊 *التقرير ({i+1}/{len(parts)}):*\n\n```\n{part}\n```",
                parse_mode="Markdown",
            )
    else:
        await sender.reply_text(
            f"📊 *تقرير التشخيص:*\n\n```\n{report_text}\n```",
            parse_mode="Markdown",
        )

    for screenshot in report.screenshots[-5:]:
        try:
            from telegram import InputFile
            with open(screenshot["path"], "rb") as f:
                await sender.reply_photo(
                    photo=InputFile(f),
                    caption=f"📸 {screenshot['caption'][:200]}",
                )
        except Exception as e:
            log.warning(f"فشل إرسال صورة: {e}")


def get_system_info() -> dict:
    from config import config
    return {
        "HEADLESS": config.HEADLESS,
        "PROXY_ENABLED": config.PROXY_ENABLED,
        "CAPTCHA_USERID": config.CAPTCHA_USERID[:20] + "..." if config.CAPTCHA_USERID else "❌ فاضي",
        "CAPTCHA_APIKEY": "✅ موجود" if config.CAPTCHA_APIKEY else "❌ فاضي",
        "DB_PATH": config.DB_PATH,
        "CHROME_PROFILE_DIR": config.CHROME_PROFILE_DIR,
    }
