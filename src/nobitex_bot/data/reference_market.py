"""جمع‌آوری دادهٔ مرجع از بازارهای جهانی (فاز A نقشهٔ راه چندبازاره).

فقط جمع‌آوری و ذخیره‌سازیه — طبق اصل بخش ۲ سند معماری («منبع خارجی نباید
وابستگی سخت باشه») و بخش ۱۹ («کشف رابطه نباید مستقیم وارد تصمیم بشه»،
هیچ سیگنال معامله‌ای فعلاً به این دیتا وابسته نیست. هدف اینه که بعد از
چند هفته جمع‌آوری، با Walk-Forward واقعی سنجیده بشه آیا رفتار بایننس
واقعاً ارزش پیش‌بینی برای نوبیتکس داره یا نه، قبل از اینکه وارد استراتژی بشه.
"""

from __future__ import annotations

import logging

from nobitex_bot.data.storage import Storage
from nobitex_bot.exchange.binance_public_client import BinancePublicClient
from nobitex_bot.exchange.endpoints import parse_symbol_to_currency_pair

logger = logging.getLogger(__name__)

REFERENCE_EXCHANGE = "binance"


def nobitex_symbol_to_binance_symbol(nobitex_symbol: str) -> str | None:
    """معادل بایننس یک نماد نوبیتکس (فرمت udf، مثل ``BTCIRT``) رو حدس می‌زنه.

    فقط برای بازارهای ساده کار می‌کنه — نمادهای مقیاسی مثل ``1M_BTTIRT``
    معادل قطعی روی بایننس ندارن (قرارداد نام‌گذاری متفاوته)، پس ``None``
    برمی‌گردن و در جمع‌آوری رد می‌شن."""
    try:
        src, _dst = parse_symbol_to_currency_pair(nobitex_symbol)
    except ValueError:
        return None
    if "_" in src:
        return None
    return f"{src.upper()}USDT"


class ReferenceMarketCollector:
    def __init__(self, storage: Storage, client: BinancePublicClient | None = None) -> None:
        self.storage = storage
        self.client = client or BinancePublicClient()

    def collect(self, nobitex_symbols: list[str], resolution: str, limit: int = 200) -> int:
        """برای هر نماد نوبیتکس، معادل بایننسش (اگه وجود داشته باشه) رو
        می‌گیره و ذخیره می‌کنه. خطای هر نماد جدا catch می‌شه — یک بازار
        مشکل‌دار نباید بقیه یا چرخهٔ اصلی معامله رو متوقف کنه."""
        total_saved = 0
        for nobitex_symbol in nobitex_symbols:
            binance_symbol = nobitex_symbol_to_binance_symbol(nobitex_symbol)
            if binance_symbol is None:
                continue
            try:
                candles = self.client.get_klines(binance_symbol, resolution, limit=limit)
            except Exception:
                logger.exception(
                    "جمع‌آوری دادهٔ مرجع برای %s (بایننس %s) ناموفق بود", nobitex_symbol, binance_symbol
                )
                continue
            if not candles:
                continue
            saved = self.storage.upsert_reference_candles(REFERENCE_EXCHANGE, binance_symbol, resolution, candles)
            total_saved += saved
        if total_saved:
            logger.info("دادهٔ مرجع بایننس ذخیره شد: %d کندل (%d نماد)", total_saved, len(nobitex_symbols))
        return total_saved
