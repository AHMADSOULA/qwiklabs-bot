import asyncio
from utils.logger import get_logger

log = get_logger("CaptchaSolver")


# ✅ متغير عام: نخزنو فيه الحل اللي كتبعتو
# {user_id: solution}
PENDING_CAPTCHA = {}


async def detect_and_solve_captcha(page, user_id: int = None,
                                    sender=None, context=None) -> str:
    """
    يكتشف CAPTCHA، يصورها، يرسلها للمستخدم، وينتظر الحل.
    يرجع الحل إذا لقاه، None إذا ما كانش.
    """
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
                        return {
                            found: true,
                            src: img.src.substring(0, 100),
                            width: img.naturalWidth,
                            height: img.naturalHeight,
                        };
                    }
                }
                return { found: false };
            }
        """)

        if not captcha_info.get("found"):
            log.info("✅ ما كاينش CAPTCHA")
            return None

        log.info(f"🚨 CAPTCHA مطلوب!")

        # 📸 نصور الصورة
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

        # ✅ إذا ما عندناش sender، نرجع None
        if not sender or not user_id:
            log.warning("⚠️ ما عنديش sender ولا user_id")
            return None

        # 📤 نرسل الصورة للمستخدم
        from telegram import InputFile
        import os

        if not os.path.exists(img_path):
            return None

        # ⏸️ نحطو الحل فـ PENDING
        PENDING_CAPTCHA[user_id] = {
            "solution": None,
            "waiting": True,
        }

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

        # ⏳ ننتظر الحل (max 5 minutes)
        log.info(f"⏳ ننتظر الحل من user {user_id}...")
        for i in range(60):  # 60 × 5 = 300s = 5 min
            await asyncio.sleep(5)

            data = PENDING_CAPTCHA.get(user_id, {})
            if data.get("solution"):
                solution = data["solution"]
                PENDING_CAPTCHA.pop(user_id, None)
                log.info(f"✅ استقبلت الحل: {solution}")
                return solution

            if not data.get("waiting"):
                log.warning("⚠️ المستخدم ألغى")
                PENDING_CAPTCHA.pop(user_id, None)
                return None

        log.error("⏰ Timeout — ما وصلش الحل")
        PENDING_CAPTCHA.pop(user_id, None)
        return None

    except Exception as e:
        log.error(f"فشل CAPTCHA: {e}")
        return None


def set_captcha_solution(user_id: int, solution: str):
    """يتنادى من handlers ملي المستخدم يبعت الحل"""
    if user_id in PENDING_CAPTCHA:
        PENDING_CAPTCHA[user_id]["solution"] = solution.strip()
        PENDING_CAPTCHA[user_id]["waiting"] = False
        log.info(f"✅ الحل تسجل: {solution}")
        return True
    return False


def cancel_captcha(user_id: int):
    """يتنادى ملي المستخدم يلغي"""
    if user_id in PENDING_CAPTCHA:
        PENDING_CAPTCHA[user_id]["waiting"] = False
        log.info(f"🚫 تم الإلغاء")
