# 🤖 ربات دوره‌ساز عمومی تلگرام

ربات وایت‌لیبل برگزاری **دوره‌های مرحله‌ای** (هر اپیزود = رسانه + متن) با ثبت‌نام موبایلی، پیشنهاد خرید، آمار و پیام‌گروهی —
**مدیریت کامل داخل خود تلگرام** (`/admin`)، بدون پنل وب، بدون کدنویس برای دوره‌های بعدی.
موضوع دوره مهم نیست: هر دوره‌ای (آموزشی، مهارتی،...) با هر تعداد اپیزود، حتی چند دوره هم‌زمان.

> **۹۵ تست سبز** (`python -m pytest tests/ -q -p no:asyncio`) — جزئیات: `docs/TEST_REPORT.md`

---

## ۱. ویژگی‌ها

**سمت کاربر**
- `/start` ← ارسال شماره با دکمه (تایپی قبول نیست، کانتکت جعلی رد می‌شود) ← ثبت نام
- کاتالوگ دوره‌ها با درصد پیشرفت هر دوره؛ ورود به دوره و طی مرحله‌به‌مرحله (قفل سروری، دورزدن ناممکن)
- پخش متن/ویدیو/عکس/ویس، نوار پیشرفت واقعی؛ ورود = دیده شدن (بدون دکمه اضافه)
- **یک صفحهٔ منوی شناور**: گشتن بین منوها هیچ پیام تازه‌ای نمی‌سازد (پیام قبلی درجا ویرایش می‌شود)؛ محتوای اپیزودها دست‌نخورده می‌ماند تا بتوانی برگردی و مرور کنی
- دکمه‌های کهنه (اپیزود حذف‌شده) هشدار می‌دهند و جمع می‌شوند، به‌جای اینکه بی‌جواب بمانند
- پیشنهاد خرید هوشمند (قابل تنظیم: بعد از اپیزود N یا همیشه) + دکمه «پرداخت کردم»
- `/episodes` و `/help` متناسب با وضعیت کاربر؛ هیچ ورودی اشتباهی بی‌پاسخ نمی‌ماند

**سمت مدیر (`/admin` — فقط `ADMIN_IDS`)**
- 📚 دوره‌ها: ساخت/حذف/فعال‌سازی، انتخاب دوره جاری مدیریت
- 📺 اپیزود: ساخت متنی/رسانه‌ای، ویرایش عنوان و متن، ترتیب، حذف با تأیید
- 📝 ویرایش **۲۰ متن** ربات — از جمله **برچسب دکمه‌ها** — لحن و زبان دلخواه، بدون کد
- ✏️ دکمهٔ «متن‌های این صفحه»: فقط برای ادمین نمایش داده می‌شود، پس همان متنی را که می‌بینی همان‌جا عوض می‌کنی و با «🔙 بازگشت» زنده نتیجه‌اش را می‌بینی. هر متنِ تغییرکرده با «↩️ بازگشت به پیش‌فرض» برمی‌گردد
- 🎁 پیشنهاد خرید per-course یا سراسری + آمار دیده/کلیک/خرید
- 💰 تأیید/رد دستی خرید (خریدار خودکار خبردار می‌شود)
- 📣 پیام تکی/همه/گروه مرحله‌ای با پیش‌نمایش تعداد گیرنده + تأیید (ارسال خودکار هر ۳۰ ثانیه)
- 👥 جست‌وجو/فیلتر کاربران، پروفایل با پیشرفت همه دوره‌ها و تایم‌لاین رویدادها
- 📊📈 آمار لحظه‌ای، قیف و ریزش هر اپیزود

---

## ۲. معماری (خلاصه)

```
کاربر/مدیر (تلگرام، PTB v21)
   ├─ bot/handlers.py        نمای کاربر (کاتالوگ، منو، اپیزود، گیت مرحله‌ای)
   └─ bot/admin_handlers.py  نمای مدیر (/admin) + bot/admin_texts.py
            ↓ هر دو فقط این‌ها را صدا می‌زنند ↓
modules/  (۱۸ ماژول مستقل — قلب قابل‌استفاده مجدد)
   config · database · logging_mod · telegram_core · screens · buttons · users ·
   phone_verification · course_engine · progress · events · analytics ·
   offers · messaging · notifications · admin · backup · settings
            ↓
SQLite (schema.sql نسخه ۱ + database/migrations/ نسخه‌دار با schema_version)
```

- **قانون طلایی**: منطق در `modules/`، سلیقه در `bot/` و دیتابیس. ربات بعدی = همین ماژول‌ها + سیم‌کشی تازه.
- **کاتالوگ ماژول‌ها**: `modules/registry.json` (نسخه ۳) + شناسنامه هر ماژول در `../MODULES.md` و `../modules/*.md` (سطح اکوسیستم، نه داخل این پروژه)
- پیشرفت تاریخچه‌محور و per-course است؛ آمار از رویدادهای واقعی محاسبه می‌شود؛ `track()` خراب هرگز فلو کاربر را نمی‌شکند.
- خرید = درخواست `pending` + تأیید مدیر (بدون وب‌سرور).

---

## ۳. اجرای محلی (ویندوز، ۵ دقیقه)

```bat
pip install -r requirements.txt
copy config\.env.example .env
notepad .env
```

| کلید | از کجا | اجباری؟ |
|---|---|---|
| `BOT_TOKEN` | @BotFather ← `/newbot` | ✅ |
| `ADMIN_IDS` | @userinfobot ← عدد `Id` (چندتا با کاما) | ✅ |
| `OWNER_EMAIL` | ایمیل خودت | ✅ |
| `DATABASE_PATH` | پیش‌فرض `data/bot.db` | نه |

```bat
python -m bot.main
```

اولین اجرا دیتابیس خالی می‌سازد. بعد در تلگرام از اکانت مدیر `/admin` بزن و دوره‌ات را بساز.

---

## ۴. استقرار روی سرور (لینوکس — پیشنهادی)

```bash
# 1) کاربر جدا + کد
sudo useradd -m botuser && sudo -u botuser -i
git clone <repo> coursebot && cd coursebot

# 2) محیط ایزوله
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3) تنظیمات (فقط همین یک فایل سکرت دارد)
cp config/.env.example .env && nano .env   # توکن/ادمین/ایمیل واقعی

# 4) تست smoke
python -m pytest tests/ -q -p no:asyncio
python -m modules.backup backup            # مطمئن شو بکاپ کار می‌کند

# 5) سرویس دائمی (systemd): /etc/systemd/system/coursebot.service
```
```ini
[Unit]
Description=Telegram course bot
After=network-online.target

[Service]
User=botuser
WorkingDirectory=/home/botuser/coursebot
ExecStart=/home/botuser/coursebot/.venv/bin/python -m bot.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable --now coursebot
journalctl -u coursebot -f          # مشاهده لاگ زنده
```

**بکاپ خودکار روزانه** (crontab کاربر `botuser`):
```bash
0 3 * * * /home/botuser/coursebot/.venv/bin/python -m modules.backup backup >> /home/botuser/backup.log 2>&1
```
بازیابی (فقط با ربات خاموش!):
```bash
sudo systemctl stop coursebot
python -m modules.backup restore data/backups/bot-<ts>.db --i-stopped-the-bot
sudo systemctl start coursebot
```

**آپدیت نسخه جدید**: `git pull` ← تست ← `sudo systemctl restart coursebot` (مایگریشن‌ها خودکار اعمال می‌شوند).

**گزینه ویندوز سرور**: همین مراحل با Task Scheduler (trigger: at startup) و `pythonw -m bot.main`؛ لاگ را با `>> bot.log 2>&1` بگیر.

**مانیتورینگ**: هر روز `/admin` ← 📊 آمار (کاربران امروز، صف پیام، خریدهای pending). اگر پیام‌ها در «⏳ در صف» ماندند یعنی ربات خوابیده — سرویس را چک کن.

---

## ۵. مدیریت روزانه (خلاصه — کاملش: `docs/ADMIN_GUIDE.md`)

| کار | مسیر |
|---|---|
| دوره تازه (۲۰ اپیزودی؟ همین‌طور) | 📚 ← ➕ ← اپیزودها (ساخت تکی یا گروهی با متن) |
| عوض کردن لحن ربات | همان صفحه‌ای که خودت می‌بینی → ✏️ متن‌های این صفحه (یا 📝 متن‌ها) |
| پیشنهاد فروش | 🎁 (زمان `episode:N` یا `always`، همین دوره/همه) |
| تأیید خرید | 💰 خریدها |
| یادآوری به غایبان | 📣 ← گروهی ← `inactive` + روز |
| فهمیدن ریزش | 📈 (هر اپیزود با ریزش بالا = محتواش را بازبینی کن) |

---

## ۶. تست‌ها

```bat
python -m pytest tests/ -q -p no:asyncio     # ۹۵ تست
```

پوشش: ثبت‌نام/شماره/نام، ترتیب و قفل مرحله، ضد دورزدن و کالبک مخرب، ویرایش متن از داخل صفحه (حلقهٔ کامل + بازگشت به پیش‌فرض + غریبه رد می‌شود)، مدل صفحه (گشتن منو = صفر پیام تازه، دابل‌تپ بی‌صدا، دکمهٔ مرده، حذف ناموفق بی‌خطر، گروه بدون ویرایش)، آنالیتیکس و مخرج صفر، آفر و خرید (درخواست/تأیید/رد/dedupe)، کاتالوگ و ایزولاسیون پیشرفت، override متن‌ها، مایگریشن، بکاپ/ریستور، سکوت در برابر غریبه، ارسال واقعی صف، مقیاس ۱۱۰۰ کاربر.

---

## ۷. ساختار پروژه

```
bot/            handlers.py (کاربر) · admin_handlers.py + admin_texts.py (مدیر) · texts.py (پیش‌فرض متن‌ها) · main.py
modules/        ۱۸ ماژول + registry.json / registry.py
database/       schema.sql + migrations/002_catalog.sql
content/          (اختیاری) فایل‌های seed JSON اولین اجرا — الان خالی است؛ شروع تمیز
config/         .env.example
tests/          doubles.py (دابل‌های مشترک تلگرام) · test_modules · test_admin_bot · test_bot_ux ·
                test_catalog · test_screens · test_copy_edit · test_media_bulk · test_smart_admin ·
                test_config_resilience
docs/           ADMIN_GUIDE · INSTALL · ADD_EPISODE · API_WEBHOOKS · ARCHITECTURE · SECURITY · TEST_REPORT · MODULES(S)
```

## ۸. امنیت (خلاصه — کاملش: `docs/SECURITY.md`)

احراز مدیر = خود تلگرام (`ADMIN_IDS`)، بدون پسورد؛ سکوت در برابر غریبه؛ شماره فقط Contact واقعی؛ گیت سروری همه دسترسی‌ها؛ کوئری‌های پارامتری؛ ولیدیشن همه ورودی‌های ویزارد؛ تأییدیه قبل از حذف/ارسال گروهی؛ خرید فقط با تأیید صریح؛ لاگ بدون سکرت/موبایل. سکرت‌ها فقط در `.env` (gitignore) — هرگز کامیت نمی‌شود.

## ۹. عیب‌یابی

| علامت | علت محتمل | راه‌حل |
|---|---|---|
| `Owner configuration missing` + خروج کد ۲ | `.env` ناقص (عمدی، امنیتی) | ۳ مقدار اجباری را پر کن |
| `/admin` جواب نمی‌دهد | آیدی‌ات در `ADMIN_IDS` نیست / ربات ری‌استارت نشده | آیدی @userinfobot را چک کن، سرویس را restart کن |
| پیام گروهی در «⏳ در صف» مانده | ربات خاموش است | سرویس/`python -m bot.main` را بالا بیاور |
| ویدیو برای کاربر نیامد | رسانه اپیزود `file_id` ندارد یا نامعتبر | از `/admin` دوباره فایل را در همان اپیزود بگذار |
| بعد از آپدیت خطای ستون ناموجود | مایگریشن ناقص | `data/bot.db` را بکاپ بگیر، ربات را ری‌استارت کن (مایگریشن خودکار) |
| کاربر قدیمی دوره نمی‌بیند | `current_course` ندارد | خودش از «📚 دوره‌ها» انتخاب می‌کند |

## ۱۰. برای ربات بعدی

1. `modules/registry.json` را بخوان 2. ماژول لازم را reuse کن 3. قابلیت واقعاً تازه را ماژول مستقل کن + در registry ثبت کن 4. متن/دوره را از تلگرام بساز، نه با کد.
