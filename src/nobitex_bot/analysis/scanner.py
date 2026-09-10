"""اسکن همهٔ بازارهای فعال نوبیتکس و رتبه‌بندی فرصت‌های معاملاتی.

معیار رتبه‌بندی طبق سند پروژه: نوسان، حجم (volumeSrc/volumeDst)، و قدرت
سیگنال. هر سه معیار بین بازارهای مختلف (که مقیاس قیمتشون کاملاً متفاوته)
نرمالایز می‌شن تا قابل‌مقایسه باشن، سپس با وزن‌های قابل‌تنظیم ترکیب می‌شن.

قدرت سیگنال از توافق سه اندیکاتور مستقل به دست میاد (نه یک اندیکاتور
تنها): جهت EMA9/EMA21 (روند)، فاصلهٔ RSI از ۵۰ (مومنتوم)، و علامت
هیستوگرام MACD. هرچی این سه بیشتر هم‌جهت باشن، سیگنال قوی‌تر و
قابل‌اعتمادتره.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from decimal import Decimal

from nobitex_bot.analysis.indicators import (
    MIN_CANDLES_FOR_INDICATORS,
    candles_to_dataframe,
    compute_indicators,
    drop_unclosed_last_candle,
)
from nobitex_bot.data.market_data import MarketDataService
from nobitex_bot.exchange.endpoints import (
    RESOLUTION_SECONDS,
    is_irt_quoted_symbol,
    stats_symbol_to_udf_symbol,
)
from nobitex_bot.exchange.models import MarketStat

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    symbol: str
    last_price: Decimal
    volume_dst: Decimal
    atr_pct: float
    signal_direction: str  # "bullish" | "bearish" | "neutral"
    signal_strength: float  # 0..1 — میزان توافق اندیکاتورها
    composite_score: float = 0.0


def _min_max_normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


class MarketScanner:
    def __init__(
        self,
        market_data: MarketDataService,
        resolution: str = "60",
        lookback_candles: int = 200,
        weight_volatility: float = 0.3,
        weight_volume: float = 0.3,
        weight_signal: float = 0.4,
        max_symbols: int | None = 40,
        max_spread_pct: float | None = None,
    ) -> None:
        """``max_symbols``: قید rate limit نوبیتکس برای کندل تاریخی (۲۰
        درخواست در دقیقه، محافظه‌کارانه چون مستند دقیقی در دسترس نبود) به این
        معنیه که اسکن *همهٔ* بازارهای نوبیتکس (چند صد نماد، شامل بازارهای
        کم‌حجم بی‌فایده) یک چرخه رو می‌تونه ساعت‌ها طول بده — دقیقاً چیزی که
        در اولین اجراهای واقعی روی GitHub Actions اتفاق افتاد (هر اجرا ۸۰-۱۴۰
        دقیقه). قبل از گرفتن کندل، فقط ``max_symbols`` بازار با بیشترین حجم
        معاملهٔ اخیر (``volumeDst``) تحلیل می‌شن — هم منطقی‌تره (بازارهای
        کم‌حجم فرصت معاملاتی قابل‌اتکایی نیستن) هم چرخه رو در چند دقیقه نگه
        می‌داره. ``None`` یعنی بدون محدودیت (رفتار قبلی، فقط برای تست/دیباگ)."""
        if resolution == "1":
            raise ValueError("resolution=1 مجاز نیست — اسکالپ ممنوعه طبق سند پروژه")
        self.market_data = market_data
        self.resolution = resolution
        self.lookback_candles = lookback_candles
        self.weight_volatility = weight_volatility
        self.weight_volume = weight_volume
        self.weight_signal = weight_signal
        self.max_symbols = max_symbols
        self.max_spread_pct = max_spread_pct

    @staticmethod
    def spread_pct(stat: MarketStat) -> float | None:
        """فاصلهٔ خرید/فروش به‌صورت کسری از ``bestBuy``. ``None`` یعنی
        ``market/stats`` برای این بازار دفتر سفارش معتبری نداده (بازار
        خالی) — در این حالت قضاوتی نمی‌کنیم."""
        if stat.best_buy is None or stat.best_sell is None or stat.best_buy <= 0:
            return None
        if stat.best_sell < stat.best_buy:
            return None
        return float((stat.best_sell - stat.best_buy) / stat.best_buy)

    @staticmethod
    def _comparable_volume(symbol: str, udf_stats: dict[str, MarketStat]) -> Decimal:
        """حجم معاملهٔ نماد را به یک واحد مشترک (ریال) برمی‌گردونه.

        ``volumeDst`` واحدش ارز مقصدِ همون بازاره: برای بازار ریالی **ریال** و
        برای بازار تتری **تتر** — دو مقیاس با اختلاف مرتبهٔ ~۱۰⁷. مرتب‌سازی
        خام روی این عدد یعنی هیچ بازار تتری‌ای هیچ‌وقت وارد ``max_symbols``
        نمی‌شه (در دادهٔ واقعی بازار، ۴۰ نماد اول ۱۰۰٪ ریالی بودن). این فقط
        یک ناترازی آماری نیست، اثر اقتصادی داره: بازارهای تتری در پلهٔ کارمزد
        پایه ۰.۱۳٪ taker دارن در مقابل ۰.۲۵٪ ریالی، و اسپردشون هم کمی
        تنگ‌تره — یعنی ~۳۸٪ اصطکاک کمتر روی نیمه‌ای از صرافی که ربات
        هیچ‌وقت نگاهش نکرده بود.

        نرخ تبدیل از خودِ ``USDTIRT`` در همون پاسخ ``market/stats`` گرفته
        می‌شه (همیشه حاضره). اگه پیدا نشد، حجم تتری دست‌نخورده برمی‌گرده —
        محافظه‌کارانه‌ترین حالت، یعنی همون رفتار قبلی، نه یک ضریب حدسی.
        """
        volume = udf_stats[symbol].volume_dst or Decimal(0)
        if not is_irt_quoted_symbol(symbol):
            usdt_stat = udf_stats.get("USDTIRT")
            rate = usdt_stat.latest if usdt_stat is not None else None
            if rate:
                return volume * rate
        return volume

    def _analyze_symbol(self, symbol: str, last_price: Decimal, volume_dst: Decimal) -> ScanResult | None:
        span_seconds = RESOLUTION_SECONDS[self.resolution] * self.lookback_candles
        now = int(time.time())
        candles = self.market_data.get_ohlc_history(symbol, self.resolution, now - span_seconds, now)
        candles = drop_unclosed_last_candle(candles, RESOLUTION_SECONDS[self.resolution], now)
        if len(candles) < MIN_CANDLES_FOR_INDICATORS:
            logger.debug("داده ناکافی برای %s (%d کندل) — رد شد", symbol, len(candles))
            return None

        df = compute_indicators(candles_to_dataframe(candles))
        last = df.iloc[-1]
        if last[["EMA_9", "EMA_21", "RSI_14", "MACDh_12_26_9", "ATRr_14"]].isna().any():
            return None

        close = last["close"]
        atr_pct = (last["ATRr_14"] / close) if close else 0.0

        trend_vote = 1 if last["EMA_9"] > last["EMA_21"] else -1
        macd_vote = 1 if last["MACDh_12_26_9"] > 0 else -1
        rsi_vote = 1 if last["RSI_14"] > 50 else (-1 if last["RSI_14"] < 50 else 0)

        raw_signal = (trend_vote + macd_vote + rsi_vote) / 3.0
        signal_direction = "bullish" if raw_signal > 0 else "bearish" if raw_signal < 0 else "neutral"

        return ScanResult(
            symbol=symbol,
            last_price=last_price,
            volume_dst=volume_dst,
            atr_pct=float(atr_pct),
            signal_direction=signal_direction,
            signal_strength=abs(raw_signal),
        )

    def scan(self, symbols: list[str] | None = None) -> list[ScanResult]:
        """همهٔ بازارها (یا لیست مشخص‌شده) رو اسکن و بر اساس امتیاز ترکیبی رتبه‌بندی می‌کنه.

        ``market/stats`` نمادها رو با فرمتی کاملاً متفاوت از ``market/udf/history``
        برمی‌گردونه (``btc-rls`` نه ``BTCIRT``) — بدون این تبدیل، هر درخواست
        کندل با همون نماد خام با خطای ۴۰۰ رد می‌شد (کشف‌شده در اولین اجرای
        واقعی روی GitHub Actions، چون این sandbox قبلاً دسترسی شبکه نداشت).
        """
        stats = self.market_data.get_all_market_stats()

        udf_stats: dict[str, MarketStat] = {}
        for raw_symbol, stat in stats.items():
            try:
                udf_symbol = stats_symbol_to_udf_symbol(raw_symbol)
            except ValueError:
                udf_symbol = raw_symbol  # از قبل به فرمت udf بوده (مثلاً تست‌ها یا فراخوانی مستقیم)
            udf_stats[udf_symbol] = stat

        if symbols is not None:
            target_symbols = symbols
        else:
            ranked_by_volume = sorted(
                udf_stats.keys(), key=lambda s: self._comparable_volume(s, udf_stats), reverse=True
            )
            target_symbols = ranked_by_volume[: self.max_symbols] if self.max_symbols is not None else ranked_by_volume

        results: list[ScanResult] = []
        for symbol in target_symbols:
            stat = udf_stats.get(symbol)
            if stat is None or stat.latest is None:
                continue
            # اسپرد بخش بزرگی از اصطکاک معامله است و ``market/stats`` (که از
            # قبل صدا زده شده) مجانی می‌دش. بازارهای کم‌عمق **قبل از** خرج‌کردن
            # یک درخواست کندل رد می‌شن — هم هزینه رو کم می‌کنه هم سهمیهٔ
            # rate limit رو آزاد می‌کنه برای بازارهای قابل‌معامله.
            if self.max_spread_pct is not None:
                spread = self.spread_pct(stat)
                if spread is None or spread > self.max_spread_pct:
                    logger.debug("اسپرد %s خارج از حد مجاز (%s) — رد شد", symbol, spread)
                    continue
            try:
                result = self._analyze_symbol(symbol, stat.latest, stat.volume_dst or Decimal(0))
            except Exception:
                logger.exception("خطا در تحلیل %s — رد شد", symbol)
                continue
            if result is not None:
                results.append(result)

        if not results:
            return []

        volatility_norm = _min_max_normalize([r.atr_pct for r in results])
        volume_norm = _min_max_normalize(
            [math.log10(float(r.volume_dst) + 1.0) for r in results]
        )

        for i, result in enumerate(results):
            result.composite_score = (
                self.weight_volatility * volatility_norm[i]
                + self.weight_volume * volume_norm[i]
                + self.weight_signal * result.signal_strength
            )

        return sorted(results, key=lambda r: r.composite_score, reverse=True)
