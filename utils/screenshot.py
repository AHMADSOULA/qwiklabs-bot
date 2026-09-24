import os
import time
from utils.logger import get_logger

log = get_logger("Screenshot")

SCREENSHOT_DIR = "/app/data/screenshots"


def ensure_dir():
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)


async def take_screenshot(page, name: str) -> str:
    ensure_dir()
    timestamp = int(time.time())
    safe_name = "".join(c for c in name if c.isalnum() or c in "-_")[:40]
    filepath = f"{SCREENSHOT_DIR}/{timestamp}_{safe_name}.png"
    try:
        await page.screenshot(path=filepath, full_page=False)
        log.info(f"📸 Screenshot: {filepath}")
        return filepath
    except Exception as e:
        log.error(f"فشل التقاط screenshot: {e}")
        return None


async def get_page_html(page) -> str:
    """يرجع HTML ديال الصفحة (للتصحيح)."""
    try:
        html = await page.content()
        # احفظ في ملف
        ensure_dir()
        timestamp = int(time.time())
        filepath = f"{SCREENSHOT_DIR}/{timestamp}_page.html"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        return html[:1000]
    except Exception as e:
        return f"فشل استخراج HTML: {e}"
