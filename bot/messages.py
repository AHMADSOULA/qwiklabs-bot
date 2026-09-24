WELCOME = """
👋 *مرحباً بك في بوت Google Cloud → Cloud Run*

📌 *طريقة الاستعمال:*
1. افتح Google Skills واختر Lab
2. انسخ رابط SSO من الصفحة
3. أرسل الرابط هنا
4. البوت سيدخل تلقائياً

⚠️ الرابط صالح 5 ساعات فقط.
"""

PROCESSING = "⏳ جاري المعالجة..."
SUCCESS = "✅ *تم بنجاح!*\n\n{url}"
FAILED = "❌ *فشل*\n\n{error}"
NO_URL = "⚠️ أرسل رابط SSO صحيح من skills.google"
STATUS_TEMPLATE = "📊 *آخر {count} مهام:*\n\n{jobs}"
JOB_LINE = "• `#{id}` — {status_emoji} {status} — {date}"
