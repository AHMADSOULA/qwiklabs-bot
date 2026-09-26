import asyncio
import aiohttp
import base64
import json
from utils.logger import get_logger

log = get_logger("CaptchaSolver")

PENDING_CAPTCHA = {}


async def has_captcha(page) -> bool:
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


async def detect_and_solve_captcha(page, user_id: int = None, sender=None, context=None) -> str:
    from config import config

    if not await has_captcha(page):
        log.info("✅ ما كاينش CAPTCHA")
        return None

    log.info("🚨 CAPTCHA مطلوبة!")

    captcha_img = None
    for sel in ['img[src*="captcha"]', 'img[alt*="captcha" i]', 'img[id*="captcha"]', 'img[src*="Captcha"]']:
        try:
            el = page.locator(sel).first
            if await el.count() > 0 and await el.is_visible():
                captcha_img = el
                break
        except Exception:
            continue

    if not captcha_img:
        return None

    img_path = "/app/data/screenshots/captcha.png"
    await captcha_img.screenshot(path=img_path)

    if config.CAPTCHA_MODE == "truecaptcha":
        solution = await _solve_truecaptcha(img_path, config.CAPTCHA_USERID, config.CAPTCHA_APIKEY)
    else:
        solution = await _solve_manual(user_id, sender, img_path)

    if not solution:
        return None

    for sel in ['input[name="ca"]', 'input[id="ca"]', 'input[name="captcha"]',
                'input[type="text"][aria-label*="Type the text" i]']:
        try:
            inp = page.locator(sel).first
            if await inp.count() == 0 or not await inp.is_visible():
                continue
            await inp.click()
            await asyncio.sleep(0.3)
            await inp.fill("")
            await asyncio.sleep(0.2)
            await inp.fill(solution)
            await asyncio.sleep(0.5)

            for btn_sel in ['#captchaNext', 'button:has-text("Next")', 'input[type="submit"]', '#identifierNext']:
                try:
                    btn = page.locator(btn_sel).first
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click()
                        await asyncio.sleep(3)
                        return solution
                except Exception:
                    continue
            return solution
        except Exception:
            continue
    return None


async def _solve_truecaptcha(img_path: str, userid: str, apikey: str) -> str:
    if not userid or not apikey:
        return None
    try:
        with open(img_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()

        payload = {
            "userid": userid,
            "apikey": apikey,
            "data": b64,
            "case": "mixed",
            "numeric": "false",
            "len_str": "6",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.apitruecaptcha.org/one/gettext",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                text = await resp.text()
                log.info(f"📥 TrueCaptcha: {text[:200]}")
                if resp.status != 200:
                    return None
                data = json.loads(text)
                result = data.get("result")
                if result:
                    log.info(f"✅ الحل: {result}")
                    return result.strip()
                return None
    except Exception as e:
        log.error(f"فشل TrueCaptcha: {e}")
        return None


async def _solve_manual(user_id: int, sender, img_path: str) -> str:
    if not sender or not user_id:
        return None

    from telegram import InputFile
    import os
    if not os.path.exists(img_path):
        return None

    PENDING_CAPTCHA[user_id] = {"solution": None, "waiting
