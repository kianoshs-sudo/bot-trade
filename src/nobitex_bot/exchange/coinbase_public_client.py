"""کلاینت عمومی REST کوینبیس — منبع دادهٔ مرجع فاز A (جایگزین بایننس).

⚠️ چرا کوینبیس نه بایننس: اولین اجرای واقعی روی GitHub Actions نشون داد
``api.binance.com`` با کد ۴۵۱ (Unavailable For Legal Reasons) هر درخواستی
از IP آمریکایی (ران‌رهای GitHub Actions روی دیتاسنتر Azure US هستن) رو
مسدود می‌کنه — این محدودیت رگولاتوری خودِ بایننسه (کاربر آمریکایی باید از
Binance.US استفاده کنه، نه binance.com)، نه مشکل کد یا شبکه. کوینبیس یک
صرافی آمریکایی‌ه و همچین بلاکی نداره.

هیچ کلید/توکنی لازم نداره (endpoint عمومی candles). هر خطایی (نماد
ناشناخته، rate limit، قطعی شبکه) فقط لاگ می‌شه و لیست خالی برمی‌گرده —
این کلاینت هیچ‌وقت نباید چرخهٔ اصلی معاملهٔ نوبیتکس رو متوقف کنه.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal

import requests

from nobitex_bot.exchange.models import Candle

logger = logging.getLogger(__name__)

COINBASE_BASE_URL = "https://api.exchange.coinbase.com"

# رزولوشن‌های پروژه (نوبیتکس) -> granularity کوینبیس (ثانیه). کوینبیس فقط
# همین شش مقدار رو می‌پذیره — رزولوشن‌های بدون معادل دقیق (۳۰، ۱۸۰، ...) رد می‌شن.
RESOLUTION_TO_GRANULARITY: dict[str, int] = {
    "5": 300, "15": 900, "60": 3600, "360": 21600, "D": 86400,
}


class CoinbasePublicClient:
    def __init__(self, session: requests.Session | None = None, max_retries: int = 3, timeout: int = 15) -> None:
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self.timeout = timeout

    def get_candles(self, product_id: str, resolution: str) -> list[Candle]:
        """کندل‌های اخیر یک محصول کوینبیس (مثل ``BTC-USD``). در هر خطا
        (نماد ناشناخته، rate limit، قطعی شبکه) به‌جای exception، فقط لاگ
        می‌کنه و لیست خالی برمی‌گردونه."""
        granularity = RESOLUTION_TO_GRANULARITY.get(resolution)
        if granularity is None:
            logger.warning("رزولوشن %s معادل کوینبیس نداره — نماد %s رد شد", resolution, product_id)
            return []

        params = {"granularity": granularity}
        attempt = 0
        while True:
            try:
                response = self.session.get(
                    f"{COINBASE_BASE_URL}/products/{product_id}/candles", params=params, timeout=self.timeout
                )
            except requests.RequestException as exc:
                attempt += 1
                if attempt > self.max_retries:
                    logger.warning("خطای شبکهٔ کوینبیس برای %s بعد از %d تلاش: %s", product_id, self.max_retries, exc)
                    return []
                time.sleep(min(2**attempt, 10))
                continue

            if response.status_code in (400, 404):
                logger.info("کوینبیس نماد %s رو نمی‌شناسه — رد شد", product_id)
                return []

            if response.status_code == 429:
                attempt += 1
                if attempt > self.max_retries:
                    logger.warning("کوینبیس rate limit برای %s بعد از %d تلاش — رد شد", product_id, self.max_retries)
                    return []
                time.sleep(min(2**attempt, 30))
                continue

            if response.status_code >= 500:
                attempt += 1
                if attempt > self.max_retries:
                    logger.warning("خطای سرور کوینبیس برای %s بعد از %d تلاش — رد شد", product_id, self.max_retries)
                    return []
                time.sleep(min(2**attempt, 10))
                continue

            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                logger.warning("خطای کوینبیس برای %s: %s — رد شد", product_id, exc)
                return []

            # فیلدهای عددی کوینبیس (برخلاف بایننس) رشته نیستن — با parse_float=str
            # قبل از رسیدن به Decimal از عبور مخفی از float جلوگیری می‌شه.
            raw = response.json(parse_float=str)
            # هر ردیف: [time, low, high, open, close, volume] — ترتیب فیلدها با
            # بایننس فرق داره؛ ترتیب زمانی هم نزولیه (جدیدترین اول).
            return [
                Candle(
                    timestamp=int(row[0]),
                    open=Decimal(row[3]),
                    high=Decimal(row[2]),
                    low=Decimal(row[1]),
                    close=Decimal(row[4]),
                    volume=Decimal(row[5]),
                )
                for row in raw
            ]
