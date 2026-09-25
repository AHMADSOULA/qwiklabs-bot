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
        log.info(f"📸 {filepath}")
        return filepath
    except Exception as e:
        log.error(f"فشل screenshot: {e}")
        return None
