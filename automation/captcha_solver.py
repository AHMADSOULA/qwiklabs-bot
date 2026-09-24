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
                    if resp.status != 200:
                        log.error(f"فشل: HTTP {resp.status}")
                        return None
                    data = json.loads(text)
                    result = data.get("result")
                    if result:
                        log.info(f"✅ TrueCaptcha حل: {result}")
                        return result.strip()
                    return None
        except Exception as e:
            log.error(f"فشل TrueCaptcha: {e}")
            return None


async def detect_and_solve_captcha(page, userid: str, apikey: str) -> bool:
    try:
        captcha_img = None
        for sel in [
            'img[src*="captcha"]',
            'img[alt*="captcha" i]',
            '#captchaImage',
            'img#captcha',
            'div[role="img"] img',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    captcha_img = el
                    log.info(f"🔍 لقيت CAPTCHA: {sel}")
                    break
            except Exception:
                continue

        if not captcha_img:
            return False

        log.info("🚨 CAPTCHA مطلوب! نحلو بـ TrueCaptcha...")
        img_path = "/app/data/screenshots/captcha.png"
        await captcha_img.screenshot(path=img_path)

        solver = CaptchaSolver(userid, apikey)
        solution = await solver.solve_image_captcha(img_path, length=6)

        if not solution:
            log.error("❌ ما قدرتش نحل CAPTCHA")
            return False

        for sel in [
            'input[name="ca"]',
            'input[id="ca"]',
            'input[type="text"][aria-label*="Type the text" i]',
            'input[type="text"][aria-label*="characters" i]',
            '#captcha',
            'input[name="captcha"]',
        ]:
            try:
                inp = page.locator(sel).first
                if await inp.count() > 0 and await inp.is_visible():
                    await inp.click()
                    await inp.fill("")
                    await inp.fill(solution)

                    for btn_sel in [
                        '#captchaNext',
                        'button:has-text("Next")',
                        'input[type="submit"]',
                    ]:
                        try:
                            btn = page.locator(btn_sel).first
                            if await btn.count() > 0:
                                await btn.click()
                                await asyncio.sleep(4)
                                return True
                        except Exception:
                            continue
                    return True
            except Exception:
                continue
        return False
    except Exception as e:
        log.error(f"فشل كشف CAPTCHA: {e}")
        return False
