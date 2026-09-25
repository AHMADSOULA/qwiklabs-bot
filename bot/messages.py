WELCOME = """
👋 *مرحباً بك في Qwiklabs → Cloud Run*

📌 *طريقة الاستعمال:*
1. افتح Google Skills واختر Lab
2. انسخ رابط SSO
3. أرسل الرابط هنا
4. البوت سيدخل تلقائياً
5. ينشر على Cloud Run

⚙️ *الإعدادات:*
🐳 `docker.io/ajndjd2/ahmed-vip1`
📦 `ahmed-vip1`
🌍 `us-central1`
💾 `2Gi` | ⚙️ `2vCPU`
"""

PROCESSING = "⏳ جاري المعالجة..."
FAILED = "❌ *فشل*\n\n{error}"
NO_URL = "⚠️ أرسل رابط SSO صحيح"
STATUS_TEMPLATE = "📊 *آخر {count} مهام:*\n\n{jobs}"
JOB_LINE = "• `#{id}` — {status_emoji} {status} — {date}"
