"""جمع‌آوری دادهٔ مرجع از بازارهای جهانی (فاز A نقشهٔ راه چندبازاره).

فقط جمع‌آوری و ذخیره‌سازیه — طبق اصل بخش ۲ سند معماری («منبع خارجی نباید
وابستگی سخت باشه») و بخش ۱۹ («کشف رابطه نباید مستقیم وارد تصمیم بشه»،
هیچ سیگنال معامله‌ای فعلاً به این دیتا وابسته نیست. هدف اینه که بعد از
چند هفته جمع‌آوری، با Walk-Forward واقعی سنجیده بشه آیا رفتار بازار مرجع
واقعاً ارزش پیش‌بینی برای نوبیتکس داره یا نه، قبل از اینکه وارد استراتژی بشه.

⚠️ کوینبیس، نه بایننس: اولین اجرای واقعی روی GitHub Actions نشون داد
``api.binance.com`` هر درخواستی از IP آمریکایی (ران‌رهای GitHub Actions)
رو با کد ۴۵۱ (محدودیت رگولاتوری خودِ بایننس) رد می‌کنه. کوینبیس یک صرافی
آمریکایی‌ه و این بلاک رو نداره.
"""

from __future__ import annotations

import logging

from nobitex_bot.data.storage import Storage
from nobitex_bot.exchange.coinbase_public_client import CoinbasePublicClient
from nobitex_bot.exchange.endpoints import parse_symbol_to_currency_pair

logger = logging.getLogger(__name__)

REFERENCE_EXCHANGE = "coinbase"


def nobitex_symbol_to_coinbase_symbol(nobitex_symbol: str) -> str | None:
    """معادل کوینبیس یک نماد نوبیتکس (فرمت udf، مثل ``BTCIRT``) رو حدس می‌زنه.

    فقط برای بازارهای ساده کار می‌کنه — نمادهای مقیاسی مثل ``1M_BTTIRT``
    معادل قطعی روی کوینبیس ندارن (قرارداد نام‌گذاری متفاوته)، پس ``None``
    برمی‌گردن و در جمع‌آوری رد می‌شن."""
    try:
        src, _dst = parse_symbol_to_currency_pair(nobitex_symbol)
    except ValueError:
        return None
    if "_" in src:
        return None
    return f"{src.upper()}-USD"


class ReferenceMarketCollector:
    def __init__(self, storage: Storage, client: CoinbasePublicClient | None = None) -> None:
        self.storage = storage
        self.client = client or CoinbasePublicClient()

    def collect(self, nobitex_symbols: list[str], resolution: str) -> int:
        """برای هر نماد نوبیتکس، معادل کوینبیسش (اگه وجود داشته باشه) رو
        می‌گیره و ذخیره می‌کنه. خطای هر نماد جدا catch می‌شه — یک بازار
        مشکل‌دار نباید بقیه یا چرخهٔ اصلی معامله رو متوقف کنه."""
        total_saved = 0
        for nobitex_symbol in nobitex_symbols:
            coinbase_symbol = nobitex_symbol_to_coinbase_symbol(nobitex_symbol)
            if coinbase_symbol is None:
                continue
            try:
                candles = self.client.get_candles(coinbase_symbol, resolution)
            except Exception:
                logger.exception(
                    "جمع‌آوری دادهٔ مرجع برای %s (کوینبیس %s) ناموفق بود", nobitex_symbol, coinbase_symbol
                )
                continue
            if not candles:
                continue
            saved = self.storage.upsert_reference_candles(REFERENCE_EXCHANGE, coinbase_symbol, resolution, candles)
            total_saved += saved
        if total_saved:
            logger.info("دادهٔ مرجع کوینبیس ذخیره شد: %d کندل (%d نماد)", total_saved, len(nobitex_symbols))
        return total_saved
