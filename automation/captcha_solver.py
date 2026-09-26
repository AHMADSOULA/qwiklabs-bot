import asyncio
import aiohttp
import base64
import json
from utils.logger import get_logger

log = get_logger("CaptchaSolver")


async def has_captcha(page) -> bool:
    """يتحقق واش كاين CAPTCHA فـ الصفحة"""
    try:
        return await page.evaluate("""
            () => {
                for (const img of document.querySelectorAll('img')) {
                    if (img.offsetParent === null) continue;
                    const s = (img.src || '').toLowerCase();
                    const a = (img.alt || '').toLowerCase();
                    const i = (img.id || '').toLowerCase();
                    if (s.includes('captcha') || a.includes('captcha') || i.includes('captcha')) return true;
                }
                for (const inp of document.querySelectorAll('input')) {
                    if (inp.offsetParent === null) continue;
                    const n = (inp.name || '').toLowerCase();
                    const i = (inp.id || '').toLowerCase();
                    const al = (inp.getAttribute('aria-label') || '').toLowerCase();
                    if (n === 'ca' || i === 'ca' || n === 'captcha' || i === 'captcha' ||
                        al.includes('type the text')) return true;
                }
                return false;
            }
        """)
    except Exception:
        return False


async def detect_and_solve_captcha(page, userid: str = "", apikey: str = "") -> str:
    """
    يحل CAPTCHA عبر TrueCaptcha API.
    """
    # ✅ إذا ما مرسلناش credentials، نجيبوهم من config
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

    # ✅ نصور الصورة
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
        log.warning("⚠️ ما لقيتش img")
        return None

    img_path = "/app/data/screenshots/captcha.png"
    await captcha_img.screenshot(path=img_path)
    log.info(f"📸 حفظت: {img_path}")

    # ✅ نحلها عبر TrueCaptcha
    solution = await _solve_truecaptcha(img_path, userid, apikey)

    if not solution:
        log.warning("⚠️ ما قدرتش نحل CAPTCHA")
        return None

    log.info(f"✅ الحل: {solution}")

    # ✅ نكتب الحل
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

                # ✅ نضغط Next
                for btn_sel in [
                    '#captchaNext',
                    'button:has-text("Next")',
                    'input[type="submit"]',
                    'button[type="submit"]',
                    '#identifierNext',
                ]:
                    try:
                        btn = page.locator(btn_sel).first
                        if await btn.count() > 0 and await btn.is_visible():
                            await btn.click()
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
    """يحل CAPTCHA عبر TrueCaptcha API"""
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


# ✅ متغيرات للتوافق (ما كتستعملش دابا)
def set_captcha_solution(user_id: int, solution: str) -> bool:
    return False


def cancel_captcha(user_id: int):
    pass
