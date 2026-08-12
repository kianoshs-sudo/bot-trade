from decimal import Decimal

from nobitex_bot.analysis.indicators import candles_to_dataframe, compute_indicators, drop_unclosed_last_candle
from nobitex_bot.exchange.models import Candle


def _c(ts):
    return Candle(timestamp=ts, open=Decimal("1"), high=Decimal("1"), low=Decimal("1"), close=Decimal("1"), volume=Decimal("1"))


def make_trending_candles(n: int, start_price: float, direction: int, accel: float = 0.03) -> list[Candle]:
    """کندل‌های یک روند شتاب‌دار (نه خطی با گام ثابت). ``direction`` باید ۱ (صعودی)
    یا ‎-1‎ (نزولی) باشه. مسیر قیمت به‌صورت ``start + direction * accel * i**1.5``
    شتاب می‌گیره تا مومنتوم (و در نتیجه هیستوگرام MACD) در طول کل روند
    هم‌جهت باقی بمونه — برخلاف یک روند خطی یا نمایی-نزولی که در اون شتاب
    (momentum) در بازهٔ طولانی رقیق می‌شه و می‌تونه علامت هیستوگرام رو
    برخلاف جهت روند برگردونه (یک نکتهٔ ریاضی دربارهٔ MACD، نه باگ کد)."""
    if direction not in (1, -1):
        raise ValueError("direction باید 1 یا -1 باشه")
    candles = []
    prev_close = start_price
    for i in range(n):
        close = start_price + direction * accel * (i**1.5)
        open_ = prev_close
        high = max(open_, close) * 1.002
        low = min(open_, close) * 0.998
        candles.append(
            Candle(
                timestamp=1_700_000_000 + i * 3600,
                open=Decimal(str(round(open_, 6))),
                high=Decimal(str(round(high, 6))),
                low=Decimal(str(round(low, 6))),
                close=Decimal(str(round(close, 6))),
                volume=Decimal("100"),
            )
        )
        prev_close = close
    return candles


def test_candles_to_dataframe_preserves_order_and_converts_to_float():
    candles = make_trending_candles(5, 100.0, direction=1)
    df = candles_to_dataframe(list(reversed(candles)))

    assert df["timestamp"].is_monotonic_increasing
    assert isinstance(df["close"].iloc[0], float)


def test_compute_indicators_uptrend_produces_bullish_signals():
    candles = make_trending_candles(60, 100.0, direction=1)
    df = compute_indicators(candles_to_dataframe(candles))
    last = df.iloc[-1]

    assert last["EMA_9"] > last["EMA_21"]
    assert last["RSI_14"] > 50
    assert last["MACDh_12_26_9"] > 0


def test_compute_indicators_downtrend_produces_bearish_signals():
    candles = make_trending_candles(60, 200.0, direction=-1)
    df = compute_indicators(candles_to_dataframe(candles))
    last = df.iloc[-1]

    assert last["EMA_9"] < last["EMA_21"]
    assert last["RSI_14"] < 50
    assert last["MACDh_12_26_9"] < 0


def test_drop_unclosed_last_candle_removes_still_forming_bar():
    """اگه بازهٔ کندل آخر هنوز تموم نشده (ts + resolution_seconds > now)، این
    یعنی udf/history کندل در حال شکل‌گیریِ لحظهٔ درخواست رو هم برگردونده —
    باید حذف بشه."""
    now = 1_700_010_000
    candles = [_c(1_700_000_000), _c(1_700_003_600), _c(1_700_007_200)]  # آخری هنوز باز است (تا 1_700_010_800)

    result = drop_unclosed_last_candle(candles, resolution_seconds=3600, now=now)

    assert [c.timestamp for c in result] == [1_700_000_000, 1_700_003_600]


def test_drop_unclosed_last_candle_keeps_fully_closed_bars():
    now = 1_700_020_000
    candles = [_c(1_700_000_000), _c(1_700_003_600), _c(1_700_007_200)]  # همه از قبل بسته شدن

    result = drop_unclosed_last_candle(candles, resolution_seconds=3600, now=now)

    assert [c.timestamp for c in result] == [1_700_000_000, 1_700_003_600, 1_700_007_200]


def test_drop_unclosed_last_candle_handles_empty_list():
    assert drop_unclosed_last_candle([], resolution_seconds=3600, now=1_700_000_000) == []
