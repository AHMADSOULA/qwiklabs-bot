import asyncio
import aiohttp
import base64
import json
from utils.logger import get_logger

log = get_logger("CaptchaSolver")


class TrueCaptchaSolver:
    """يحل CAPTCHA عبر TrueCaptcha API"""

    def __init__(self):
        from config import config
        self.userid = config.CAPTCHA_USERID
        self.apikey = config.CAPTCHA_APIKEY
        self.api_url = "https://api.apitruecaptcha.org/one/gettext"

    async def solve(self, image_path: str, length: int = 6) -> str:
        if not self.userid or not self.apikey:
            log.warning("⚠️ ما عنديش TrueCaptcha credentials")
            return None

        try:
            with open(image_path, "rb") as f:
                image_data = f.read()
            b64 = base64.b64encode(image_data).decode()
            log.info(f"📤 TrueCaptcha ({len(image_data)} bytes)...")

            payload = {
                "userid": self.userid,
                "apikey": self.apikey,
                "data": b64,
                "case": "mixed",
                "numeric": "false",
                "len_str": str(length),
                "tag": "qwiklabs-bot",
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.api_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    text = await resp.text()
                    log.info(f"📥 TrueCaptcha: {text[:300]}")

                    if resp.status != 200:
                        log.error(f"فشل HTTP {resp.status}")
                        return None

                    try:
                        data = json.loads(text)
                    except Exception:
                        return None

                    result = data.get("result")
                    if result:
                        log.info(f"✅ الحل: {result}")
                        return result.strip()
                    else:
                        log.error(f"ما كاينش result: {data}")
                        return None

        except asyncio.TimeoutError:
            log.error("⏰ Timeout")
            return None
        except Exception as e:
            log.error(f"فشل TrueCaptcha: {e}")
            return None


async def detect_and_solve_captcha_api(page) -> str:
    """
    يكتشف CAPTCHA ويحلها عبر TrueCaptcha API.
    يرجع النص إذا نجح.
    """
    try:
        from utils.screenshot import take_screenshot
        await take_screenshot(page, "captcha_check")

        # ✅ 1. نبحث عن صورة CAPTCHA
        captcha_info = await page.evaluate("""
            () => {
                const imgs = document.querySelectorAll('img');
                for (const img of imgs) {
                    if (img.offsetParent === null) continue;
                    const src = (img.src || '').toLowerCase();
                    const alt = (img.alt || '').toLowerCase();
                    const id = (img.id || '').toLowerCase();
                    const cls = (img.className || '').toString().toLowerCase();
                    if (src.includes('captcha') || alt.includes('captcha') ||
                        id.includes('captcha') || cls.includes('captcha')) {
                        return { found: true, src: img.src.substring(0, 100) };
                    }
                }
                return { found: false };
            }
        """)

        if not captcha_info.get("found"):
            log.info("✅ ما كاينش CAPTCHA")
            return None

        log.info("🚨 CAPTCHA detected — solving via TrueCaptcha...")

        # ✅ 2. نصور الصورة
        captcha_img = None
        for sel in [
            'img[src*="captcha"]',
            'img[alt*="captcha" i]',
            'img[id*="captcha"]',
            'img[class*="captcha"]',
            'img[src*="Captcha"]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    captcha_img = el
                    break
            except Exception:
                continue

        if not captcha_img:
            log.warning("⚠️ ما لقيتش img")
            return None

        img_path = "/app/data/screenshots/captcha.png"
        await captcha_img.screenshot(path=img_path)
        log.info(f"📸 حفظت: {img_path}")

        # ✅ 3. نحلها
        solver = TrueCaptchaSolver()
        solution = await solver.solve(img_path, length=6)

        if not solution:
            return None

        return solution

    except Exception as e:
        log.error(f"فشل CAPTCHA: {e}")
        return None


# ✅ دالة قديمة (للتوافق) — كتستعمل الحل اليدوي
PENDING_CAPTCHA = {}


async def detect_and_solve_captcha(page, user_id: int = None,
                                    sender=None, context=None) -> str:
    """نسخة قديمة — الحل اليدوي"""
    return await detect_and_solve_captcha_api(page)


def set_captcha_solution(user_id: int, solution: str):
    if user_id in PENDING_CAPTCHA:
        PENDING_CAPTCHA[user_id]["solution"] = solution.strip()
        PENDING_CAPTCHA[user_id]["waiting"] = False
        return True
    return False


def cancel_captcha(user_id: int):
    if user_id in PENDING_CAPTCHA:
        PENDING_CAPTCHA[user_id]["waiting"] = False
