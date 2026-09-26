"""Admin-in-Telegram copy (Persian). Presentation layer only; everything delegates to modules/*."""

MENU_TITLE = ("🛠 پنل مدیریت (تلگرام)\n"
              "اینجا همه‌چیز ربات را می‌سازی و می‌بینی. یک بخش را انتخاب کن.")
NOT_ADMIN = None  # silent ignore for non-admins (don't leak panel existence)

STATS_TITLE = "📊 آمار لحظه‌ای"
USERS_TITLE = "👥 کاربران"
USER_DETAIL_TITLE = "👤 پروفایل کاربر"
EPS_TITLE = "📺 اپیزودها"
OFFERS_TITLE = "🎁 پیشنهاد خرید"
MSG_TITLE = "📣 پیام‌رسانی"
ANALYTICS_TITLE = "📈 آنالیتیکس"

BTN_STATS = "📊 آمار"
BTN_USERS = "👥 کاربران"
BTN_EPS = "📺 اپیزودها"
BTN_OFFERS = "🎁 پیشنهاد خرید"
BTN_MSG = "📣 پیام‌رسانی"
BTN_ANALYTICS = "📈 آنالیتیکس"
BTN_BACK_MENU = "🏠 منوی مدیریت"
BTN_CANCEL = "❌ انصراف"
SAVED_NEXT = "قدم بعدی؟"

ASK_USER_QUERY = "نام، یوزرنیم، موبایل یا آیدی تلگرام را بفرست (یا انصراف):"
ASK_COURSE_TITLE = "عنوان دوره را بفرست (همانی که کاربر می‌بیند):"
ASK_COURSE_DESC = "توضیح کوتاه دوره را بفرست — یا «-» برای خالی:"
ASK_EP_TITLE = "عنوان اپیزود را بفرست (شماره‌اش خودکار داده می‌شود):"
ASK_EP_CONTENT = ("محتوای اپیزود را بفرست:\n"
                  "• متن تایپ کن = اپیزود متنی (بدون ویدیو)\n"
                  "• عکس یا ویدیو بفرست = محتوای تصویری (قدم بعد، متنش را می‌نویسی)")
ASK_EP_DESC = "متن زیر ویدیو/عکس را بنویس (توضیح اپیزود) — یا «-» برای بدون متن:"
ASK_MEDIA = "رسانه اپیزود را بفرست (عکس، ویدیو، ویس... — موقع ورود به اپیزود نشان داده می‌شود):"
ASK_OFFER_SLUG = "نام یکتای انگلیسی پیشنهاد (مثلاً vip-course):"
ASK_OFFER_TITLE = "عنوان پیشنهاد:"
ASK_OFFER_TEXT = "متن پیام پیشنهاد:"
ASK_OFFER_BUTTON = "متن دکمه خرید:"
ASK_OFFER_URL = "لینک خرید (با https://):"
ASK_OFFER_TRIGGER = "زمان نمایش: بنویس episode:15 (بعد از اتمام اپیزود ۱۵) یا always:"
ASK_MSG_TEXT = "متن پیام را بفرست (حداکثر ۴۰۰۰ حرف):"
ASK_MSG_SINGLE_ID = "ID داخلی کاربر را بفرست (همان عدد ستون ID در لیست کاربران):"
ASK_MSG_DAYS = "چند روز بی‌فعالیتی؟ (عدد بفرست، مثلاً 3):"
MSG_AUDIENCE_Q = "پیام به چه کسی ارسال شود؟"
MSG_CONFIRM = "تأیید ارسال؟"
MSG_QUEUED = "✅ در صف ارسال قرار گرفت. وضعیت را از «📣 پیام‌رسانی» ببین."
MSG_CANCELLED = "❌ انصراف داده شد."
INVALID_NUMBER = "عدد معتبر بفرست."
INVALID_URL = "لینک باید با https:// یا http:// شروع شود."
INVALID_SLUG = "نام یکتا باید انگلیسی، بدون فاصله (حروف، عدد، - و _) باشد."
INVALID_TRIGGER = "قالب درست نیست. بنویس episode:15 یا always."
SAVED = "✅ ذخیره شد."
TOGGLED = "✅ وضعیت عوض شد."
MOVED = "✅ جابه‌جا شد."
CANCELLED = "❌ انصراف داده شد. /admin"
STAGE_NAMES = {
    "registered_only": "فقط شماره داده‌ها",
    "not_started": "شروع‌نکرده‌ها",
    "finished": "تمام‌کرده‌ها",
    "customers": "خریداران",
    "offer_viewed": "پیشنهاد را دیده‌ها",
    "offer_clicked": "کلیک‌کنندگان پیشنهاد",
    "inactive": "غیرفعال‌ها",
}
STATUS_FA = {"new": "تازه (بدون شماره)", "phone_submitted": "شماره داده",
             "in_course": "داخل دوره", "finished": "تمام‌کرده", "customer": "خریدار"}
