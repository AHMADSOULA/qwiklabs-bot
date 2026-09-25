import asyncio
import aiohttp
import base64
import json
from utils.logger import get_logger

log = get_logger("CaptchaSolver")


class CaptchaSolver:
    def __init__(self, userid: str, apikey: str):
        self.userid = userid
        self.apikey = apikey
        self.api_url = "https://api.apitruecaptcha.org/one/gettext"

    async def solve_image_captcha(self, image_path: str, length: int = 6) -> str:
        if not self.userid or not self.apikey:
            log.warning("⚠️ ما عنديش TrueCaptcha credentials")
            return None
        try:
            with open(image_path, "rb") as f:
                image_data = f.read()
            b64 = base64.b64encode(image_data).decode()

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
                    log.info(f"📥 TrueCaptcha: {text[:200]}")
                    if resp.status != 200:
                        return None
                    try:
                        data = json.loads(text)
                    except Exception:
                        return None
                    result = data.get("result")
                    if result:
                        log.info(f"✅ الحل: {result}")
                        return result.strip()
                    return None
        except asyncio.TimeoutError:
            log.error("⏰ Timeout")
            return None
        except Exception as e:
            log.error(f"فشل: {e}")
            return None


async def detect_and_solve_captcha(page, userid: str, apikey: str) -> bool:
    try:
        from utils.screenshot import take_screenshot
        await take_screenshot(page, "captcha_check")

        captcha_info = await page.evaluate("""
            () => {
                const imgs = document.querySelectorAll('img');
                for (const img of imgs) {
                    const src = (img.src || '').toLowerCase();
                    const alt = (img.alt || '').toLowerCase();
                    const id = (img.id || '').toLowerCase();
                    if (src.includes('captcha') || alt.includes('captcha') ||
                        id.includes('captcha')) {
                        return { found: true };
                    }
                }
                return { found: false };
            }
        """)

        if not captcha_info.get("found"):
            log.info("✅ ما كاينش CAPTCHA")
            return False

        log.info("🚨 CAPTCHA مطلوب!")

        captcha_img = None
        for sel in [
            'img[src*="captcha"]',
            'img[alt*="captcha" i]',
            'img[id*="captcha"]',
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
            return False

        img_path = "/app/data/screenshots/captcha.png"
        await captcha_img.screenshot(path=img_path)

        solver = CaptchaSolver(userid, apikey)
        solution = await solver.solve_image_captcha(img_path, length=6)

        if not solution:
            return False

        input_filled = False
        for sel in [
            'input[name="ca"]',
            'input[id="ca"]',
            'input[name="captcha"]',
            'input[type="text"][aria-label*="Type the text" i]',
            'input[type="text"][aria-label*="characters" i]',
        ]:
            try:
                inp = page.locator(sel).first
                if await inp.count() > 0 and await inp.is_visible():
                    await inp.click()
                    await asyncio.sleep(0.3)
                    await inp.fill("")
                    await asyncio.sleep(0.2)
                    await inp.fill(solution)
                    await asyncio.sleep(0.5)
                    val = await inp.input_value()
                    if val.strip():
                        log.info(f"✍️ كتبت: {val}")
                        input_filled = True
                        break
            except Exception:
                continue

        if not input_filled:
            return False

        await take_screenshot(page, "captcha_filled")

        await asyncio.sleep(0.5)
        for sel in [
            '#captchaNext',
            'button:has-text("Next")',
            'input[type="submit"]',
            'button[type="submit"]',
            '#identifierNext',
        ]:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(4)
                    return True
            except Exception:
                continue

        return True
    except Exception as e:
        log.error(f"فشل CAPTCHA: {e}")
        return False
