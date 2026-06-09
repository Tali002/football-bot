# 🤖 بات تلگرام پیش‌بینی فوتبال

## نصب و راه‌اندازی

### پیش‌نیازها
- Python 3.10 یا بالاتر
- دسترسی به اینترنت

### مراحل

**۱. نصب کتابخانه‌ها:**
```bash
pip install -r requirements.txt
```

**۲. قرار دادن فایل‌ها:**
```
football_bot/
├── bot.py
├── service_account.json   ← فایل JSON سرویس اکانت گوگل
└── requirements.txt
```

**۳. اجرای بات:**
```bash
cd football_bot
python bot.py
```

---

## ساختار شیت مورد انتظار

| ستون | محتوا |
|------|-------|
| A | (خالی / اضافه) |
| B | ضریب |
| C | تاریخ شمسی (مثل: پنجشنبه ۲۱ خرداد) |
| D | نام بازی با ساعت (مثل: ایران vs نیوزیلند (۰۴:۳۰)) |
| E به بعد | هر دو ستون = یک نفر (ردیف ۲ = اسم، ردیف ۳+ = پیش‌بینی‌ها) |

---

## دستورات بات

| دستور | توضیح |
|-------|-------|
| `/start` | شروع و راهنما |
| `/predict` | ثبت یا ویرایش پیش‌بینی |
| `/mypredictions` | نمایش همه پیش‌بینی‌های من |
| `/cancel` | لغو عملیات جاری |

---

## نکات مهم

- **۱۰ دقیقه قبل از بازی** — بات دیگه پیش‌بینی قبول نمی‌کنه
- **ویرایش** — تا قبل از ۱۰ دقیقه می‌شه دوباره /predict زد و تغییر داد
- **فرمت نتیجه** — `۲-۱` یا `0-3` (اعداد فارسی یا انگلیسی هر دو قبوله)
- **ستون جدید** — اولین باری که هر نفر پیش‌بینی می‌ده، ستون جدیدی براش ساخته می‌شه

---

## اجرا به صورت سرویس (لینوکس)

برای اینکه بات همیشه روشن بمونه:

```bash
# ساخت سرویس systemd
sudo nano /etc/systemd/system/football-bot.service
```

محتوا:
```ini
[Unit]
Description=Football Prediction Telegram Bot
After=network.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/path/to/football_bot
ExecStart=/usr/bin/python3 bot.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable football-bot
sudo systemctl start football-bot
sudo systemctl status football-bot
```
