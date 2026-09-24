import asyncio
import aiohttp
import base64
import json
from utils.logger import get_logger

log = get_logger("CaptchaSolver")


class CaptchaSolver:
    """يحل CAPTCHA باستعمال TrueCaptcha API"""

    def __init__(self, userid: str, apikey: str):
        self.userid = userid
        self.apikey = apikey
        self.api_url = "https://api.apitruecaptcha.org/one/gettext"

    async def solve_image_captcha(self, image_path: str, length: int = 6) -> str:
        if not self.userid or not self.apikey:
            log.warning("ما عنديش TrueCaptcha credentials")
            return None

        try:
            with open(image_path, "rb") as f:
                image_data = f.read()
            b64 = base64.b64encode(image_data).decode()
            log.info(f"📤 نرسل CAPTCHA لـ TrueCaptcha ({len(image_data)} bytes)...")

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
                    log.info(f"📥 رد: {text[:300]}")

                    if resp.status != 200:
                        log.error(f"فشل: HTTP {resp.status}")
                        return None

                    try:
                        data = json.loads(text)
                    except Exception:
                        log.error(f"ما قدرتش نحلل JSON")
                        return None

                    result = data.get("result")
                    if result:
                        log.info(f"✅ TrueCaptcha حل: {result}")
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


async def detect_and_solve_captcha(page, userid: str, apikey: str) -> bool:
    """
    يكتشف CAPTCHA فـ الصفحة ويحلها.
    """
    try:
        # 🔍 نصور الصفحة كاملة أولاً (باش نشوفو)
        from utils.screenshot import take_screenshot
        await take_screenshot(page, "captcha_check")

        # 🔍 نستعملو JS باش نلقاو صورة CAPTCHA (selectors متعددة)
        captcha_found = await page.evaluate("""
            () => {
                const imgs = document.querySelectorAll('img');
                for (const img of imgs) {
                    const src = (img.src || '').toLowerCase();
                    const alt = (img.alt || '').toLowerCase();
                    const id = (img.id || '').toLowerCase();
                    const cls = (img.className || '').toString().toLowerCase();
                    if (src.includes('captcha') || alt.includes('captcha') ||
                        id.includes('captcha') || cls.includes('captcha') ||
                        src.includes('captchaimage')) {
                        return {
                            found: true,
                            src: img.src,
                            alt: img.alt,
                            id: img.id,
                            className: img.className,
                            width: img.naturalWidth,
                            height: img.naturalHeight,
                        };
                    }
                }
                return { found: false };
            }
        """)

        log.info(f"🔍 نتيجة البحث عن CAPTCHA: {captcha_found}")

        if not captcha_found.get("found"):
            log.info("✅ ما كاينش CAPTCHA")
            return False

        log.info("🚨 CAPTCHA مطلوب! نحلو...")

        # 📸 نصور الصورة ديال CAPTCHA
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
                    log.info(f"✅ لقيت img: {sel}")
                    break
            except Exception:
                continue

        if not captcha_img:
            log.warning("ما لقيتش صورة CAPTCHA بالـ selectors")
            return False

        img_path = "/app/data/screenshots/captcha.png"
        await captcha_img.screenshot(path=img_path)
        log.info(f"📸 حفظت CAPTCHA فـ {img_path}")

        # 🤖 نحلها
        solver = CaptchaSolver(userid, apikey)
        solution = await solver.solve_image_captcha(img_path, length=6)

        if not solution:
            log.error("❌ ما قدرتش نحل CAPTCHA")
            return False

        # ✍️ نكتب الحل
        for sel in [
            'input[name="ca"]',
            'input[id="ca"]',
            'input[type="text"][aria-label*="Type the text" i]',
            'input[type="text"][aria-label*="characters" i]',
            '#captcha',
            'input[name="captcha"]',
            'input[type="text"]',
        ]:
            try:
                inp = page.locator(sel).first
                if await inp.count() > 0 and await inp.is_visible():
                    log.info(f"✅ حقل CAPTCHA: {sel}")
                    await inp.click()
                    await inp.fill("")
                    await inp.fill(solution)
                    log.info(f"✍️ كتبت: {solution}")

                    # نضغط Next
                    for btn_sel in [
                        '#captchaNext',
                        'button:has-text("Next")',
                        'input[type="submit"]',
                        'button[type="submit"]',
                    ]:
                        try:
                            btn = page.locator(btn_sel).first
                            if await btn.count() > 0:
                                await btn.click()
                                log.info(f"✅ كليك Next")
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
