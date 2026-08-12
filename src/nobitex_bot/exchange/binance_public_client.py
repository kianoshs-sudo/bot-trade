"""کلاینت عمومی REST بایننس — فقط برای جمع‌آوری دادهٔ مرجع (فاز A نقشهٔ
چندبازاره‌شدن، طبق بخش ۴-۵ سند معماری).

هیچ کلید/توکنی لازم نداره (endpoint عمومی kline). طبق اصل «منبع خارجی
نباید وابستگی سخت باشه»، خطای هر نوع (شبکه، نماد ناشناخته، rate limit)
به‌جای raise کردن، فقط لاگ می‌شه و لیست خالی برمی‌گرده — این کلاینت هیچ‌وقت
نباید چرخهٔ اصلی معاملهٔ نوبیتکس رو متوقف کنه.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal

import requests

from nobitex_bot.exchange.models import Candle

logger = logging.getLogger(__name__)

BINANCE_BASE_URL = "https://api.binance.com"
KLINES_PATH = "/api/v3/klines"

# رزولوشن‌های پروژه (بخش نوبیتکس) -> بازهٔ کندل بایننس
RESOLUTION_TO_BINANCE_INTERVAL: dict[str, str] = {
    "5": "5m", "15": "15m", "30": "30m", "60": "1h",
    "180": "3h", "240": "4h", "360": "6h", "720": "12h",
    "D": "1d", "2D": "2d", "3D": "3d",
}


class BinancePublicClient:
    def __init__(self, session: requests.Session | None = None, max_retries: int = 3, timeout: int = 15) -> None:
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self.timeout = timeout

    def get_klines(self, symbol: str, resolution: str, limit: int = 200) -> list[Candle]:
        """کندل‌های اخیر یک نماد بایننس (مثل ``BTCUSDT``). در هر خطا (نماد
        ناشناخته، rate limit، قطعی شبکه) به‌جای exception، فقط لاگ می‌کنه و
        لیست خالی برمی‌گردونه."""
        interval = RESOLUTION_TO_BINANCE_INTERVAL.get(resolution)
        if interval is None:
            logger.warning("رزولوشن %s معادل بایننس نداره — نماد %s رد شد", resolution, symbol)
            return []

        params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
        attempt = 0
        while True:
            try:
                response = self.session.get(f"{BINANCE_BASE_URL}{KLINES_PATH}", params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                attempt += 1
                if attempt > self.max_retries:
                    logger.warning("خطای شبکهٔ بایننس برای %s بعد از %d تلاش: %s", symbol, self.max_retries, exc)
                    return []
                time.sleep(min(2**attempt, 10))
                continue

            if response.status_code == 400:
                logger.info("بایننس نماد %s رو نمی‌شناسه — رد شد", symbol)
                return []

            if response.status_code in (429, 418):
                attempt += 1
                if attempt > self.max_retries:
                    logger.warning("بایننس rate limit برای %s بعد از %d تلاش — رد شد", symbol, self.max_retries)
                    return []
                retry_after = float(response.headers.get("Retry-After", min(2**attempt, 30)))
                time.sleep(min(retry_after, 60.0))
                continue

            if response.status_code >= 500:
                attempt += 1
                if attempt > self.max_retries:
                    logger.warning("خطای سرور بایننس برای %s بعد از %d تلاش — رد شد", symbol, self.max_retries)
                    return []
                time.sleep(min(2**attempt, 10))
                continue

            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                logger.warning("خطای بایننس برای %s: %s — رد شد", symbol, exc)
                return []

            raw = response.json()
            # هر ردیف kline بایننس: [openTime, open, high, low, close, volume, closeTime, ...]
            # open/high/low/close/volume از قبل به‌صورت رشته برمی‌گردن — تبدیل مستقیم
            # به Decimal بدون از دست دادن دقت (بدون عبور از float).
            return [
                Candle(
                    timestamp=int(row[0]) // 1000,
                    open=Decimal(row[1]),
                    high=Decimal(row[2]),
                    low=Decimal(row[3]),
                    close=Decimal(row[4]),
                    volume=Decimal(row[5]),
                )
                for row in raw
            ]
