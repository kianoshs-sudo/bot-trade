"""لایهٔ سرویس داده: کلاینت نوبیتکس + کش کوتاه‌مدت + ذخیرهٔ SQLite را ترکیب می‌کنه.

ماژول‌های بالاتر (اسکنر بازار، بک‌تست، استراتژی) باید از این سرویس
استفاده کنن، نه مستقیم از NobitexClient — تا کش‌گذاری و ذخیره‌سازی به‌طور
یکنواخت همه‌جا اعمال بشه.
"""

from __future__ import annotations

import logging
import time

from nobitex_bot.data.cache import TTLCache
from nobitex_bot.data.storage import Storage
from nobitex_bot.exchange.client import NobitexClient
from nobitex_bot.exchange.models import Candle, MarketStat, OrderBook

logger = logging.getLogger(__name__)


class MarketDataService:
    def __init__(
        self,
        client: NobitexClient | None = None,
        storage: Storage | None = None,
        cache: TTLCache | None = None,
    ) -> None:
        self.client = client or NobitexClient()
        self.storage = storage
        self.cache = cache or TTLCache(default_ttl_seconds=2.0)

    def get_all_market_stats(self, use_cache: bool = True) -> dict[str, MarketStat]:
        """آمار همهٔ بازارها — بدون فیلتر ارز، برای کاهش تعداد درخواست موقع اسکن."""
        if not use_cache:
            return self.client.get_market_stats()
        return self.cache.get_or_set("market_stats:all", self.client.get_market_stats)

    def get_orderbook_all(self, use_cache: bool = True) -> dict[str, OrderBook]:
        """اردربوک همهٔ بازارها با یک درخواست (پارامتر all)."""
        if not use_cache:
            return self.client.get_orderbook("all")
        return self.cache.get_or_set("orderbook:all", lambda: self.client.get_orderbook("all"))

    def get_ohlc_history(
        self, symbol: str, resolution: str, from_ts: int, to_ts: int, persist: bool = True
    ) -> list[Candle]:
        candles = self.client.get_ohlc_history(symbol, resolution, from_ts, to_ts)
        if persist and self.storage is not None and candles:
            self.storage.upsert_candles(symbol, resolution, candles)
        return candles

    def get_ohlc_history_chunked(
        self,
        symbol: str,
        resolution: str,
        from_ts: int,
        to_ts: int,
        chunk_seconds: int = 30 * 24 * 3600,
        sleep_between_requests: float = 1.0,
        persist: bool = True,
    ) -> list[Candle]:
        """بازهٔ طولانی (مثلاً ۱ سال) رو تکه‌تکه دانلود می‌کنه تا از پاسخ‌های خیلی بزرگ
        و فشار ناگهانی روی rate limit جلوگیری بشه. بین هر chunk حداقل فاصلهٔ زمانی
        مشخص‌شده (پیش‌فرض ۱ ثانیه) رعایت می‌شه، طبق توصیهٔ کش سمت سرور نوبیتکس."""
        all_candles: list[Candle] = []
        cursor = from_ts
        first = True
        while cursor < to_ts:
            chunk_end = min(cursor + chunk_seconds, to_ts)
            if not first:
                time.sleep(sleep_between_requests)
            first = False
            candles = self.get_ohlc_history(symbol, resolution, cursor, chunk_end, persist=persist)
            all_candles.extend(candles)
            cursor = chunk_end
        return all_candles
