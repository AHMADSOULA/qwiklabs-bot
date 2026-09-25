import asyncio
import aiohttp
import base64
from utils.logger import get_logger

log = get_logger("CaptchaSolver")


class CaptchaSolver:
    """يحل CAPTCHA باستعمال CapSolver API"""

    def __init__(self, apikey: str):
        self.apikey = apikey
        self.create_url = "https://api.capsolver.com/createTask"
        self.result_url = "https://api.capsolver.com/getTaskResult"

    async def solve_image_captcha(self, image_path: str) -> str:
        if not self.apikey:
            log.warning("⚠️ ما عنديش CapSolver key")
            return None

        try:
            with open(image_path, "rb") as f:
                image_data = f.read()
            b64 = base64.b64encode(image_data).decode()
            log.info(f"📤 نرسل CAPTCHA ({len(image_data)} bytes)...")

            payload = {
                "clientKey": self.apikey,
                "task": {
                    "type": "ImageToTextTask",
                    "body": b64,
                },
            }

            async with aiohttp.ClientSession() as session:
                # 1. Create task
                async with session.post(self.create_url, json=payload) as resp:
                    text = await resp.text()
                    log.info(f"📥 createTask: {text[:300]}")
                    data = await resp.json()

                    if data.get("errorId") != 0:
                        log.error(f"فشل: {data.get('errorDescription')}")
                        return None

                    task_id = data.get("taskId")
                    if not task_id:
                        return None

                # 2. Poll result
                for i in range(30):
                    await asyncio.sleep(3)
                    async with session.post(
                        self.result_url,
                        json={"clientKey": self.apikey, "taskId": task_id}
                    ) as resp:
                        res = await resp.json()
                        status = res.get("status")

                        if status == "ready":
                            solution = res.get("solution", {}).get("text")
                            log.info(f"✅ الحل: {solution}")
                            return solution.strip() if solution else None
                        elif status == "processing":
                            continue
                        elif res.get("errorId") != 0:
                            log.error(f"فشل: {res.get('errorDescription')}")
                            return None
                        else:
                            log.warning(f"رد غير متوقع: {res}")
                            return None

                log.error("⏰ Timeout")
                return None

        except Exception as e:
            log.error(f"فشل CapSolver: {e}")
            return None


async def detect_and_solve_captcha(page, userid: str, apikey: str) -> bool:
    """userid ماشي مستعمل فـ CapSolver — غير apikey"""
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

        # CapSolver يستعمل apikey فقط
        solver = CaptchaSolver(apikey)
        solution = await solver.solve_image_captcha(img_path)

        if not solution:
            return False

        # نكتب الحل
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

        # Next
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
