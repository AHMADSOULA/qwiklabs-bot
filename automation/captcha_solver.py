import asyncio
import aiohttp
import base64
from utils.logger import get_logger

log = get_logger("CaptchaSolver")

# ✅ SCTG API
SCTG_API_KEY = "Uosbi2t23tLFF7D1ro9yyX1EOJ61ER8I"
SCTG_SUBMIT = "https://api.sctg.xyz/in.php"
SCTG_RESULT = "https://api.sctg.xyz/res.php"


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
    يحل CAPTCHA عبر SCTG.xyz API.
    """
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

    # ✅ نحلها عبر SCTG
    solution = await _solve_sctg(img_path)

    if not solution:
        log.warning("⚠️ SCTG ما قدرش يحلها")
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


async def _solve_sctg(img_path: str, numeric: int = 0) -> str:
    """
    يحل CAPTCHA عبر SCTG.xyz API.
    
    ✅ يقبل: image path
    ✅ API: https://api.sctg.xyz/in.php
    """
    if not SCTG_API_KEY:
        log.warning("⚠️ ما عنديش SCTG API key")
        return None

    try:
        # ✅ نقرا الصورة
        with open(img_path, "rb") as f:
            image_data = f.read()
        b64 = base64.b64encode(image_data).decode()
        log.info(f"📤 SCTG ({len(image_data)} bytes)...")

        # ✅ نرسلو
        payload = {
            "key": SCTG_API_KEY,
            "method": "post",
            "body": b64,
            "json": 1,
            "numeric": numeric,
        }

        async with aiohttp.ClientSession() as session:
            # 1. Submit
            async with session.post(
                SCTG_SUBMIT,
                data=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                text = await resp.text()
                log.info(f"📥 SCTG submit: {text[:300]}")

                if resp.status != 200:
                    log.error(f"فشل HTTP {resp.status}")
                    return None

                try:
                    data = __import__("json").loads(text)
                except Exception:
                    return None

                if data.get("status") != 1:
                    log.error(f"فشل: {data}")
                    return None

                captcha_id = data.get("request")
                if not captcha_id:
                    return None

                log.info(f"✅ SCTG ID: {captcha_id}")

            # 2. Poll result
            for i in range(30):
                await asyncio.sleep(5)
                try:
                    async with session.get(
                        SCTG_RESULT,
                        params={
                            "key": SCTG_API_KEY,
                            "action": "get",
                            "id": captcha_id,
                            "json": 1,
                        },
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as resp:
                        text = await resp.text()
                        log.info(f"📥 SCTG result {i+1}: {text[:200]}")

                        if resp.status != 200:
                            continue

                        try:
                            data = __import__("json").loads(text)
                        except Exception:
                            continue

                        if data.get("status") == 1:
                            solution = data.get("request")
                            log.info(f"✅ SCTG حل: {solution}")
                            return solution.strip() if solution else None
                        elif data.get("request") == "CAPCHA_NOT_READY":
                            continue
                        else:
                            log.error(f"فشل: {data}")
                            return None
                except Exception as e:
                    log.warning(f"فشل poll {i+1}: {e}")
                    continue

            log.error("⏰ Timeout")
            return None

    except asyncio.TimeoutError:
        log.error("⏰ Timeout")
        return None
    except Exception as e:
        log.error(f"فشل SCTG: {e}")
        return None


# ✅ متغيرات للتوافق
def set_captcha_solution(user_id: int, solution: str) -> bool:
    return False


def cancel_captcha(user_id: int):
    pass
