# ربات معامله‌گر خودکار نوبیتکس

ربات معامله‌گر پایتونی برای صرافی نوبیتکس — استراتژی ترکیبی (تکنیکال + کوانت)، مرحله‌بندی‌شده: **بک‌تست → Paper Trading (Testnet) → معاملهٔ واقعی (فقط بعد از تایید صریح)**.

## وضعیت فازها

| فاز | وضعیت |
|---|---|
| ۰ — تحقیق روی پروژه‌های متن‌باز | ✅ انجام شد |
| ۱ — لایهٔ داده | ✅ انجام شد |
| ۲ — موتور تحلیل و اندیکاتورها | ⏳ |
| ۳ — استراتژی‌های ترکیبی | ⏳ |
| ۴ — بک‌تست | ⏳ |
| ۵ — مدیریت ریسک | ⏳ |
| ۶ — Paper Trading (Testnet) | ⏳ |
| ۷ — اجرای واقعی | 🔒 نیازمند تایید صریح کاربر |
| ۸ — لاگ‌گیری و داشبورد | ⏳ |

## نصب

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # یا requirements.txt برای فقط اجرا (بدون تست)
cp .env.example .env
# .env رو ویرایش کن — برای فاز ۱-۶ نیازی به NOBITEX_API_TOKEN نیست
```

## اجرای تست‌ها

```bash
pytest
```

## دانلود دادهٔ تاریخی (برای بک‌تست)

```bash
python scripts/fetch_historical.py --resolution 60 --days 365
```

این اسکریپت همهٔ بازارهای فعال رو شناسایی می‌کنه و کندل‌های ۱ سالهٔ اخیر (تایم‌فریم ۱ ساعته، قابل تغییر) رو در `data/market_data.sqlite` ذخیره می‌کنه. کندل‌های دقیقه‌ای (resolution < 60) فقط از ابتدای ۱۴۰۱ به بعد در دسترسن — این محدودیت به‌طور خودکار در کد لحاظ شده.

## ساختار پروژه

```
src/nobitex_bot/
├── config.py              # تنظیمات از environment variables
├── exchange/
│   ├── client.py          # کلاینت HTTP نوبیتکس (Decimal، rate limit، retry/backoff)
│   ├── rate_limiter.py     # sliding-window rate limiter + احترام به backOff سرور
│   ├── endpoints.py        # ثابت‌های endpoint، محدودیت نرخ، قیدهای SmallOrder/BadPrice
│   └── models.py           # مدل‌های Decimal-based (MarketStat, Candle, OrderBook)
├── data/
│   ├── market_data.py     # سرویس داده (client + cache + storage)
│   ├── storage.py          # ذخیره‌سازی SQLite (پرتابل، بدون وابستگی به OS خاص)
│   └── cache.py            # کش کوتاه‌مدت (هم‌سو با کش سمت سرور نوبیتکس)
└── utils/logging.py
scripts/fetch_historical.py  # CLI دانلود دادهٔ تاریخی
tests/                       # یونیت‌تست (mock — بدون نیاز به اتصال شبکه)
```

## نکات مهم دربارهٔ فاز ۱

- ⚠️ **فقط خلاصهٔ prompt پروژه در دسترس بوده، نه فایل کامل مستندات رسمی نوبیتکس.** مقادیر method/path/rate-limit در `exchange/endpoints.py` دقیقاً از همون خلاصه گرفته شدن. قبل از فاز ۶ (Paper Trading روی Testnet) حتماً یک تست دستی واقعی روی `market/stats` و `market/udf/history` بزن و در صورت اختلاف (مثلاً متد HTTP یا نام فیلد پاسخ)، فقط کافیه `endpoints.py` رو اصلاح کنی — بقیهٔ کد به این جزئیات وابسته نیست.
- آدرس Testnet در سند به‌صورت `testnetapiv2.nobitex.ir` اومده بود؛ در تحقیق فاز ۰ نسخهٔ `testnetapi.nobitex.ir` (بدون v2) هم دیده شد — این هم باید موقع فاز ۶ verify بشه (از طریق env قابل تغییره، نیازی به تغییر کد نیست).
- تمام مقادیر پولی با `Decimal` پردازش می‌شن؛ در SQLite هم به‌صورت TEXT ذخیره می‌شن (نه REAL) تا هیچ گرد‌کردن اعشاری اتفاق نیفته.
- Rate limiting به‌صورت per-endpoint (sliding window) پیاده شده و در پاسخ ۴۲۹ دقیقاً به مقدار `backOff` سرور صبر می‌کنه (نه یک عدد ثابت حدسی).
- درس‌های فاز ۰ (partial fill، duplicate order، rate-limit circuit breaker) در فازهای ۵ و ۷ اعمال می‌شن؛ لایهٔ داده فعلی فقط endpointهای عمومی (بدون توکن) رو پوشش می‌ده.

## امنیت

- `.env` هرگز commit نمی‌شه (در `.gitignore`)
- کلید API هیچ‌وقت داخل کد یا این ریپو قرار نمی‌گیره
- فاز ۷ (اجرای واقعی) فقط بعد از تایید صریح کاربر و با کلید محدود به `READ,TRADE` (بدون `WITHDRAW`) فعال می‌شه
