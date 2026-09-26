import asyncio
import aiohttp
import base64
import json
from utils.logger import get_logger

log = get_logger("CaptchaSolver")

# ✅ pending captcha solutions (للحل اليدوي)
PENDING_CAPTCHA = {}


async def has_captcha(page) -> bool:
    """يتحقق واش كاين CAPTCHA"""
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


async def detect_and_solve_captcha(page, userid: str = "", apikey: str = "",
                                    user_id: int = None, sender=None) -> str:
    """
    يحل CAPTCHA:
    1. TrueCaptcha (أوتوماتيك)
    2. إذا فشل → حل يدوي (يبعت الصورة للمستخدم)
    """
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

    # ============================================
    # ✅ 1. نلقاو صورة CAPTCHA
    # ============================================
    captcha_img = None
    for sel in [
        'img[src*="captcha"]',
        'img[alt*="captcha" i]',
        'img[id*="captcha"]',
        'img[class*="captcha"]',
        'img[src*="Captcha"]',
        'div[role="img"] img',
        'canvas',
    ]:
        try:
            els = await page.locator(sel).all()
            for el in els:
                if await el.is_visible():
                    box = await el.bounding_box()
                    if box and box["width"] > 50 and box["height"] > 20:
                        captcha_img = el
                        log.info(f"✅ لقيت CAPTCHA: {sel}")
                        break
            if captcha_img:
                break
        except Exception:
            continue

    if not captcha_img:
        log.warning("⚠️ ما لقيتش img")
        return None

    img_path = "/app/data/screenshots/captcha.png"
    try:
        await captcha_img.screenshot(path=img_path, timeout=10000)
        log.info(f"📸 حفظت: {img_path}")
    except Exception as e:
        log.error(f"فشل screenshot: {e}")
        return None

    # ============================================
    # ✅ 2. نحاول TrueCaptcha
    # ============================================
    solution = None
    if userid and apikey:
        solution = await _solve_truecaptcha(img_path, userid, apikey)

    # ============================================
    # ✅ 3. إذا TrueCaptcha فشل → حل يدوي
    # ============================================
    if not solution:
        log.warning("⚠️ TrueCaptcha فشل — نروحو للحل اليدوي")
        if sender and user_id:
            solution = await _solve_manual(user_id, sender, img_path)
        else:
            log.error("❌ ما عندناش sender/user_id للحل اليدوي")
            return None

    if not solution:
        return None

    log.info(f"✅ الحل: {solution}")

    # ============================================
    # ✅ 4. نكتب الحل
    # ============================================
    for sel in [
        'input[name="ca"]',
        'input[id="ca"]',
        'input[name="captcha"]',
        'input[id="captcha"]',
        'input[type="text"][aria-label*="Type the text" i]',
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
                            await asyncio.sleep(4)
                            return solution
                    except Exception:
                        continue
                return solution
        except Exception:
            continue
    return None


async def _solve_truecaptcha(img_path: str, userid: str, apikey: str) -> str:
    """يحل CAPTCHA عبر TrueCaptcha"""
    try:
        with open(img_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        log.info(f"📤 TrueCaptcha ({len(b64)} b64)...")

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
                    return None
                data = json.loads(text)
                result = data.get("result")
                if result:
                    log.info(f"✅ TrueCaptcha: {result}")
                    return result.strip()
                log.warning(f"⚠️ TrueCaptcha ما رجعش result: {data}")
                return None
    except Exception as e:
        log.error(f"فشل TrueCaptcha: {e}")
        return None


async def _solve_manual(user_id: int, sender, img_path: str) -> str:
    """حل يدوي — يبعت الصورة للمستخدم وينتظر"""
    try:
        from telegram import InputFile
        import os

        if not os.path.exists(img_path):
            return None

        PENDING_CAPTCHA[user_id] = {"solution": None, "waiting": True}

        with open(img_path, "rb") as f:
            await sender.reply_photo(
                photo=InputFile(f),
                caption="🚨 *CAPTCHA مطلوبة*\n\n📝 اكتب الحل هنا\n⏱️ عندك 5 دقائق\n❌ /cancel",
                parse_mode="Markdown",
            )

        log.info(f"⏳ ننتظر الحل من user {user_id}...")
        for i in range(60):  # 5 دقائق
            await asyncio.sleep(5)
            data = PENDING_CAPTCHA.get(user_id, {})
            if data.get("solution"):
                sol = data["solution"]
                PENDING_CAPTCHA.pop(user_id, None)
                log.info(f"✅ الحل اليدوي: {sol}")
                return sol
            if not data.get("waiting"):
                PENDING_CAPTCHA.pop(user_id, None)
                return None

        PENDING_CAPTCHA.pop(user_id, None)
        return None
    except Exception as e:
        log.error(f"فشل الحل اليدوي: {e}")
        return None


def set_captcha_solution(user_id: int, solution: str) -> bool:
    """يتنادى من handlers ملي المستخدم يبعت الحل"""
    if user_id in PENDING_CAPTCHA:
        PENDING_CAPTCHA[user_id]["solution"] = solution.strip()
        PENDING_CAPTCHA[user_id]["waiting"] = False
        return True
    return False


def cancel_captcha(user_id: int):
    if user_id in PENDING_CAPTCHA:
        PENDING_CAPTCHA[user_id]["waiting"] = False
