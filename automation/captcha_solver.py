import asyncio
from utils.logger import get_logger

log = get_logger("CaptchaSolver")

PENDING_CAPTCHA = {}


async def detect_and_solve_captcha(page, user_id: int = None,
                                    sender=None, context=None) -> str:
    """يحل CAPTCHA يدوياً — يرسل الصورة للمستخدم وينتظر الحل"""
    try:
        from utils.screenshot import take_screenshot
        await take_screenshot(page, "captcha_check")

        # 🔍 نبحث عن CAPTCHA
        captcha_info = await page.evaluate("""
            () => {
                const imgs = document.querySelectorAll('img');
                for (const img of imgs) {
                    const src = (img.src || '').toLowerCase();
                    const alt = (img.alt || '').toLowerCase();
                    const id = (img.id || '').toLowerCase();
                    const cls = (img.className || '').toString().toLowerCase();
                    if (src.includes('captcha') || alt.includes('captcha') ||
                        id.includes('captcha') || cls.includes('captcha')) {
                        return { found: true };
                    }
                }
                return { found: false };
            }
        """)

        if not captcha_info.get("found"):
            log.info("✅ ما كاينش CAPTCHA")
            return None

        log.info("🚨 CAPTCHA مطلوب!")

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

        # ✅ إذا ما عندناش sender → نرجع None
        if not sender or not user_id:
            log.warning("⚠️ ما عنديش sender/user_id")
            return None

        # 📤 نرسل الصورة
        from telegram import InputFile
        import os
        if not os.path.exists(img_path):
            return None

        PENDING_CAPTCHA[user_id] = {"solution": None, "waiting": True}

        with open(img_path, "rb") as f:
            await sender.reply_photo(
                photo=InputFile(f),
                caption=(
                    "🚨 *CAPTCHA مطلوب*\n\n"
                    "📝 اكتب الحل هنا (النص اللي كيبان فـ الصورة)\n"
                    "⏱️ عندك 5 دقائق\n"
                    "❌ للإلغاء: `/cancel`"
                ),
                parse_mode="Markdown",
            )

        # ⏳ ننتظر الحل
        log.info(f"⏳ ننتظر الحل من user {user_id}...")
        for i in range(60):  # 5 دقائق
            await asyncio.sleep(5)
            data = PENDING_CAPTCHA.get(user_id, {})
            if data.get("solution"):
                solution = data["solution"]
                PENDING_CAPTCHA.pop(user_id, None)
                log.info(f"✅ استقبلت الحل: {solution}")
                return solution
            if not data.get("waiting"):
                PENDING_CAPTCHA.pop(user_id, None)
                return None

        log.error("⏰ Timeout")
        PENDING_CAPTCHA.pop(user_id, None)
        return None

    except Exception as e:
        log.error(f"فشل CAPTCHA: {e}")
        return None


def set_captcha_solution(user_id: int, solution: str):
    if user_id in PENDING_CAPTCHA:
        PENDING_CAPTCHA[user_id]["solution"] = solution.strip()
        PENDING_CAPTCHA[user_id]["waiting"] = False
        log.info(f"✅ الحل تسجل: {solution}")
        return True
    return False


def cancel_captcha(user_id: int):
    if user_id in PENDING_CAPTCHA:
        PENDING_CAPTCHA[user_id]["waiting"] = False
        log.info(f"🚫 تم الإلغاء")
