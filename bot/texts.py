"""User-facing bot copy: defaults + per-key override via settings (editable in /admin).

Nothing here is code logic. The shipped defaults are Persian; the admin can
change every one of them from Telegram (📝 متن‌های ربات) without a programmer.
New bots: replace DEFAULTS, keep the keys.

Every string a user can see belongs here, including button labels: an admin who
cannot reword the "🏠 منو" button has to ship a new release to change a word.
"""
from __future__ import annotations

DEFAULTS = {
    "welcome": ("به دوره خوش اومدی 🌱\n\n"
                "برای مشاهده رایگان اپیزودها، شماره موبایلت رو از طریق دکمه زیر ارسال کن"),
    "phone_button": "📱 ثبت شماره موبایل",
    "ask_name": "ممنون! حالا لطفاً اسمت رو بنویس ✍️",
    "name_saved": "عالیه ✨\n\nحالا می‌تونی اپیزودها رو به ترتیب مشاهده کنی 🌱",
    "need_phone": "اول شماره موبایلت رو با دکمه «📱 ثبت شماره موبایل» ارسال کن.",
    "typed_phone_hint": ("به نظر می‌رسه شماره رو تایپ کردی ✍️\n"
                         "تلگرام فقط شماره‌ای رو قبول می‌کنه که با دکمه زیر ارسال بشه — لطفاً روی دکمه بزن."),
    "start_first": "برای شروع، دستور /start رو بزن 🌱",
    "menu_nudge": "از دکمه‌های زیر استفاده کن 👇",
    "name_digits": "این بیشتر شبیه شماره موبایل می‌مونه تا اسم 😊\nلطفاً اسمت رو بنویس.",
    "help_new": ("راهنما 🌱\n\n۱. /start رو بزن\n۲. با دکمه «📱 ثبت شماره موبایل» شمارت رو بفرست\n"
                 "۳. اسمت رو بنویس\n۴. یک دوره انتخاب کن و اپیزودها رو به‌ترتیب ببین"),
    "help_main": ("راهنما 📖\n\n/episodes — لیست دوره‌ها و پیشرفتت\n/help — همین راهنما\n\n"
                  "اپیزودهای تمام‌شده رو می‌تونی دوباره مرور کنی."),
    "watch_first": "▶️ مشاهده اپیزود اول",
    "course_finished": "تبریک! 🎉 کل دوره رو کامل کردی.",
    "locked": "🔒 این اپیزود هنوز قفله. اول اپیزودهای قبلی رو کامل کن.",
    "episode_gone": "این اپیزود دیگر در دسترس نیست. از منو ادامه بده.",
    "invalid_callback": "درخواست نامعتبر بود. لطفاً از دکمه‌های خود ربات استفاده کن.",
    "generic_error": "مشکلی پیش اومد؛ لطفاً دوباره تلاش کن.",
    "offer_again": "🎁 مشاهده پیشنهاد ویژه",
    "paid_button": "✅ پرداخت کردم",
    "paid_received": "✅ درخواستت ثبت شد؛ بعد از تأیید، خبرت می‌کنم.",
    "catalog_title": "📚 دوره‌ها\nیکی را انتخاب کن:",
    "catalog_empty": "هنوز دوره فعالی وجود ندارد. به‌زودی برمی‌گردیم 🌱",
    "catalog_progress": "اپیزود {done} از {total}",
    # labels the user clicks. An admin reworded a course should not have to ship
    # a release to change a button.
    "unit_episode": "اپیزود",
    "btn_home": "🏠 منو",
    "btn_courses": "📚 دوره‌ها",
    "btn_next_episode": "▶️ اپیزود {next}",
}

# Admin editor metadata: (key, Persian label, max length).
TEXT_DEFS = [
    ("welcome", "پیام خوشامد", 2000),
    ("phone_button", "متن دکمه شماره موبایل", 64),
    ("ask_name", "درخواست نام", 500),
    ("name_saved", "پیام شروع دوره", 1000),
    ("need_phone", "یادآوری ثبت شماره", 500),
    ("help_new", "راهنمای کاربر تازه", 2000),
    ("help_main", "راهنمای کاربر عضو", 2000),
    ("course_finished", "پیام اتمام دوره", 500),
    ("locked", "پیام قفل بودن", 500),
    ("episode_gone", "پیام اپیزود حذف‌شده", 500),
    ("offer_again", "دکمه مشاهده پیشنهاد", 64),
    ("paid_button", "دکمه «پرداخت کردم»", 64),
    ("paid_received", "پیام ثبت درخواست خرید", 500),
    ("catalog_title", "تیتر لیست دوره‌ها", 500),
    ("catalog_empty", "متن خالی بودن دوره‌ها", 500),
    ("catalog_progress", "خط پیشرفت دوره", 100),
    ("unit_episode", "واژهٔ اپیزود", 32),
    ("btn_home", "دکمهٔ منوی اصلی", 64),
    ("btn_courses", "دکمهٔ دوره‌ها", 64),
    ("btn_next_episode", "دکمهٔ اپیزود بعدی", 64),
]

# Keys carrying {placeholders}. Rendering must not explode if an admin drops one.
TEMPLATED = {"catalog_progress": ("done", "total"), "btn_next_episode": ("next",)}


def t(db, key: str) -> str:
    """Current text for key: settings override or default."""
    from modules.settings import get
    return get(db, f"text:{key}", DEFAULTS[key])


def set_text(db, key: str, value: str) -> None:
    from modules.settings import set as _set
    _set(db, f"text:{key}", value)


def reset_text(db, key: str) -> None:
    """Drop the override and fall back to the shipped default.

    Without this, a white-label edit is a one-way door: 20 strings, no undo.
    """
    from modules.settings import delete
    delete(db, f"text:{key}")


def is_overridden(db, key: str) -> bool:
    from modules.settings import get
    return get(db, f"text:{key}", None) is not None


def render(db, key: str, **fields) -> str:
    """t() with placeholders filled. An admin is allowed to leave a {total} out
    of the progress line, so a missing or unknown field is not an error."""
    text = t(db, key)
    if "{" not in text:
        return text
    safe = {name: fields.get(name, "") for name in TEMPLATED.get(key, ())}
    try:
        return text.format(**safe)
    except (KeyError, IndexError, ValueError):
        return text


# Backward-compatible aliases (equal to defaults).
WELCOME = DEFAULTS["welcome"]
PHONE_BUTTON = DEFAULTS["phone_button"]
ASK_NAME = DEFAULTS["ask_name"]
NAME_SAVED = DEFAULTS["name_saved"]
NEED_PHONE_FIRST = DEFAULTS["need_phone"]
TYPED_PHONE_HINT = DEFAULTS["typed_phone_hint"]
START_FIRST = DEFAULTS["start_first"]
MENU_NUDGE = DEFAULTS["menu_nudge"]
NAME_DIGITS = DEFAULTS["name_digits"]
HELP_NEW = DEFAULTS["help_new"]
HELP_MAIN = DEFAULTS["help_main"]
WATCH_FIRST = DEFAULTS["watch_first"]
COURSE_FINISHED = DEFAULTS["course_finished"]
LOCKED_EPISODE = DEFAULTS["locked"]
INVALID_CALLBACK = DEFAULTS["invalid_callback"]
GENERIC_ERROR = DEFAULTS["generic_error"]
OFFER_AGAIN = DEFAULTS["offer_again"]
