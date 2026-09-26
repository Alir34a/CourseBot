# نصب و اجرا

[← README](../README.md) · [راهنمای مدیر](ADMIN_GUIDE.md) · [افزودن اپیزود](ADD_EPISODE.md) · [معماری](ARCHITECTURE.md) · [امنیت](SECURITY.md) · [وب‌هوک فروش](API_WEBHOOKS.md) · [تست‌ها](TEST_REPORT.md)

ربات یک برنامهٔ polling است: خودش به تلگرام وصل می‌شود و منتظر پیام می‌ماند. پس
وب‌سرور، دامنه یا SSL لازم نیست — فقط یک ماشین همیشه‌روشن و پایتون.

نیازمندی: **پایتون ۳.۱۱ یا بالاتر** و اکانت تلگرام.

---

## ۱. آماده‌سازی (روی هر سیستم‌عاملی)

```bash
git clone <آدرس-ریپو> coursebot
cd coursebot
python -m venv .venv
```

venv را فعال کن:

| سیستم | دستور |
|---|---|
| ویندوز (PowerShell) | `.venv\Scripts\Activate.ps1` |
| ویندوز (cmd) | `.venv\Scripts\activate.bat` |
| لینوکس / مک | `source .venv/bin/activate` |

```bash
pip install -r requirements.txt
```

اگر در ویندوز PowerShell complains کرد که اجرای اسکریپت محدود است:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## ۲. تنظیمات

```bash
cp config/.env.example .env      # ویندوز: copy config\.env.example .env
```

سه مقدار اجباری‌اند؛ بقیه پیش‌فرض دارند:

| کلید | از کجا |
|---|---|
| `BOT_TOKEN` | [@BotFather](https://t.me/BotFather) ← `/newbot` |
| `ADMIN_IDS` | [@userinfobot](https://t.me/userinfobot) ← عدد `Id`. چندتا با کاما |
| `OWNER_EMAIL` | ایمیل خودت |

اگر این سه تا پر نشده باشند ربات با پیام خطا و کد `2` خارج می‌شود — عمدی است، تا
با توکن خالی بالا نیاید.

`.env` در `.gitignore` است و کامیت نمی‌شود.

## ۳. تست قبل از اجرا

```bash
python -m pytest tests/ -q -p no:asyncio
```

## ۴. اجرا

```bash
python -m bot.main
```

بار اول دیتابیس خالی ساخته می‌شود و مایگریشن‌ها خودکار اجرا می‌شوند (اجرای دوباره
هم امن است). بعد در تلگرام `/admin` بزن و دوره و اپیزودهایت را بساز.

---

# اجرای دائمی

## لینوکس — systemd (توصیه‌شده)

ربات باید با ری‌استارت سرور بالا بیاید. یک کاربر جدا بساز:

```bash
sudo useradd -m -s /bin/bash botuser
sudo -u botuser -i
```

بعد داخل اکانت `botuser` (نه root):

```bash
git clone <آدرس-ریپو> ~/coursebot
cd ~/coursebot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config/.env.example .env
nano .env          # سه مقدار را پر کن
```

خروج. حالا فایل سرویس:

```bash
sudo nano /etc/systemd/system/coursebot.service
```

```ini
[Unit]
Description=CourseBot telegram bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=botuser
WorkingDirectory=/home/botuser/coursebot
ExecStart=/home/botuser/coursebot/.venv/bin/python -m bot.main
Restart=always
RestartSec=10

# سخت‌گیری: ربات به جز پوشهٔ خودش و فایل دیتابیس، به چیزی نیاز ندارد
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/botuser/coursebot/data

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now coursebot
sudo systemctl status coursebot
journalctl -u coursebot -f        # لاگ زنده
```

برای تغییر کد: `git pull` بعد `sudo systemctl restart coursebot`.

## ویندوز — Task Scheduler (بدون نصب ابزار اضافه)

```powershell
New-ScheduledTaskAction `
  -Execute "C:\...\coursebot\.venv\Scripts\pythonw.exe" `
  -Argument "-m bot.main" `
  -WorkingDirectory "C:\...\coursebot"
```

`pythonw.exe` است نه `python.exe` — پنجرهٔ کنسول باز نمی‌شود.
برای اجرای خودکار بعد از بوت، در Task Scheduler یک Trigger از نوع
**At startup** بساز و گزینهٔ **Run whether user is logged on or not** را تیک بزن.

راه جایگزین اگر بخواهی لایدار و مدیریت تمیزتر باشد، [NSSM](https://nssm.cc/)
است؛ Task Scheduler بدون نصب چیز اضافه کار می‌کند ولی لاگ را جمع نمی‌کند.

برای لاگ در ویندوز، خروجی را به فایل برگردان:

```powershell
python -m bot.main >> bot.log 2>&1
```

## بکاپ خودکار (لینوکس)

```bash
crontab -e
```

```cron
0 3 * * * /home/botuser/coursebot/.venv/bin/python -m modules.backup backup >> /home/botuser/backup.log 2>&1
```

هر شب ساعت ۳ یک کپی در `data/backups/` ساخته می‌شود.

بازیابی **فقط با ربات خاموش**:

```bash
sudo systemctl stop coursebot
python -m modules.backup list
python -m modules.backup restore data/backups/bot-<timestamp>.db --i-stopped-the-bot
sudo systemctl start coursebot
```

---

## چه چیزی پشتیبانی نمی‌شود

**Docker ندارد.** اگر می‌خواهی، می‌شود اضافه کرد، ولی برای یک برنامهٔ تک‌پروسه‌ای
که فقط SQLite دارد، systemd و venv ساده‌تر و کم‌دردسرترند.

---

## چک‌لیست قبل از استفادهٔ واقعی

- [ ] تست‌ها سبز است
- [ ] هر سه مقدار `.env` پر شده
- [ ] دوره و اپیزودها ساخته شده
- [ ] متن‌های ربات بازبینی شده (`/admin` → 📝 متن‌ها)
- [ ] مسیر «پرداخت کردم ← تأیید» یک بار تست شده
- [ ] اولین بکاپ گرفته شده
