# خرید و رویدادها (بدون وب‌سرور)

## مسیر خرید (تأیید دستی مدیر)
1. کاربر واجد شرایط پیشنهاد را می‌بیند (`purchase_offer_viewed`) و روی لینک می‌زند (`clicked`).
2. بعد از پرداخت، «✅ پرداخت کردم» → درخواست `pending` + ایونت `purchase_started` + پیام فوری به مدیر.
3. مدیر در «💰 خریدها» تأیید/رد می‌کند → `purchase_completed` (+ وضعیت `customer`) یا `purchase_declined`.
4. خریدار پیام نتیجه را خودکار می‌گیرد. تاریخچه در همان بخش است.

## ایونت‌های استاندارد (modules/events)
user_registered، phone_submitted، name_submitted، episode_started،
episode_completed، course_completed، purchase_offer_viewed/clicked،
purchase_started/completed/declined، user_inactive.
(ایونت‌های part_* در کتابخانه مانده‌اند ولی ربات دیگر تولیدشان نمی‌کند.)
`track()` resilient است: خطای event-store هرگز flow کاربر را نمی‌شکند.
ایونت جدید = فقط یک ثابت تازه.

## نکته فنی
`offers.record_purchase()` (با سکرت مشترک) برای اتصال‌های برنامه‌نویسی‌شده آینده نگه داشته شده؛
فعلاً مسیر رسمی، تأیید دستی از تلگرام است.
