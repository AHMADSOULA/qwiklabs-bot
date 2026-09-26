import asyncio
import aiohttp
import base64
import json
from utils.logger import get_logger

log = get_logger("CaptchaSolver")


async def has_captcha(page) -> bool:
    """يتحقق واش كاين CAPTCHA — بلا page.evaluate معقدة"""
    try:
        for sel in [
            'img[src*="captcha"]',
            'img[alt*="captcha" i]',
            'img[id*="captcha"]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    return True
            except Exception:
                continue

        for sel in [
            'input[name="ca"]',
            'input[id="ca"]',
            'input[name="captcha"]',
            'input[type="text"][aria-label*="Type the text" i]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    return True
            except Exception:
                continue

        return False
    except Exception:
        return False


async def detect_and_solve_captcha(page, userid: str = "", apikey: str = "") -> str:
    """يحل CAPTCHA عبر TrueCaptcha API"""
    if not userid or not apikey:
        try:
            from config import config
            userid = config.CAPTCHA_USERID
            apikey = config.CAPTCHA_APIKEY
        except Exception:
            pass

    if not await has_captcha(page):
        log.info("✅ ما كاينش CAPTCHA")
        return None

    log.info("🚨 CAPTCHA مطلوبة!")

    captcha_img = None
    selectors = [
        'img[src*="captcha"]',
        'img[alt*="captcha" i]',
        'img[id*="captcha"]',
        'img[class*="captcha"]',
        'img[src*="Captcha"]',
        'img[jsname*="captcha"]',
        'div[role="img"] img',
        'canvas',
    ]

    for sel in selectors:
        try:
            els = await page.locator(sel).all()
            for el in els:
                if await el.is_visible():
                    box = await el.bounding_box()
                    if box and box["width"] > 50 and box["height"] > 20:
                        captcha_img = el
                        log.info(f"✅ لقيت CAPTCHA: {sel} ({box['width']}x{box['height']})")
                        break
            if captcha_img:
                break
        except Exception:
            continue

    if not captcha_img:
        log.warning("⚠️ selectors ما خدموش — نجرب أول صورة كبيرة")
        try:
            imgs = await page.locator('img').all()
            for img in imgs:
                if await img.is_visible():
                    box = await img.bounding_box()
                    if box and box["width"] > 100 and box["height"] > 40:
                        captcha_img = img
                        log.info(f"✅ fallback img ({box['width']}x{box['height']})")
                        break
        except Exception as e:
            log.warning(f"fallback: {e}")

    if not captcha_img:
        log.error("❌ ما لقيتش img")
        return None

    img_path = "/app/data/screenshots/captcha.png"
    try:
        await captcha_img.screenshot(path=img_path, timeout=10000)
        log.info(f"📸 حفظت: {img_path}")
    except Exception as e:
        log.error(f"فشل screenshot: {e}")
        return None

    solution = await _solve_truecaptcha(img_path, userid, apikey)

    if not solution:
        log.warning("⚠️ ما قدرتش نحل CAPTCHA")
        return None

    log.info(f"✅ الحل: {solution}")

    for sel in [
        'input[name="ca"]',
        'input[id="ca"]',
        'input[name="captcha"]',
        'input[id="captcha"]',
        'input[type="text"][aria-label*="Type the text" i]',
        'input[type="text"][aria-label*="characters" i]',
    ]:
        try:
            inp = page.locator(sel).first
            if await inp.count() == 0 or not await inp.is_visible():
                continue
            log.info(f"✅ حقل CAPTCHA: {sel}")
            await inp.click()
            await asyncio.sleep(0.3)
            await inp.fill("")
            await asyncio.sleep(0.2)
            await inp.fill(solution)
            await asyncio.sleep(0.5)

            val = await inp.input_value()
            if val.strip():
                log.info(f"✍️ كتبت: {val}")

                for btn_sel in [
                    '#captchaNext',
                    '#identifierNext',
                    'button:has-text("Next")',
                    'button[type="submit"]',
                ]:
                    try:
                        btn = page.locator(btn_sel).first
                        if await btn.count() > 0 and await btn.is_visible():
                            await btn.click()
                            log.info(f"✅ كليك Next: {btn_sel}")
                            await asyncio.sleep(4)
                            return solution
                    except Exception:
                        continue
                return solution
        except Exception as e:
            log.warning(f"فشل {sel}: {e}")
            continue

    return None


async def _solve_truecaptcha(img_path: str, userid: str, apikey: str) -> str:
    if not userid or not apikey:
        log.warning("⚠️ ما عنديش TrueCaptcha credentials")
        return None

    try:
        with open(img_path, "rb") as f:
            image_data = f.read()
        b64 = base64.b64encode(image_data).decode()
        log.info(f"📤 TrueCaptcha ({len(image_data)} bytes)...")

        payload = {
            "userid": userid,
            "apikey": apikey,
            "data": b64,
            "case": "mixed",
            "numeric": "false",
            "len_str": "6",
            "tag": "qwiklabs-bot",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.apitruecaptcha.org/one/gettext",
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


def set_captcha_solution(user_id: int, solution: str) -> bool:
    return False


def cancel_captcha(user_id: int):
    pass
