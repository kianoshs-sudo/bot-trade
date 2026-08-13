import math
from decimal import Decimal

from nobitex_bot.analysis.indicators import candles_to_dataframe, compute_indicators
from nobitex_bot.exchange.models import Candle
from nobitex_bot.strategies.breakout_atr import BreakoutATRStrategy
from nobitex_bot.strategies.mean_reversion import MeanReversionStrategy
from nobitex_bot.strategies.registry import get_strategy, list_strategies
from nobitex_bot.strategies.trend_momentum_volume import TrendMomentumVolumeStrategy


def _candle(ts, o, h, l, c, v):
    return Candle(
        timestamp=ts,
        open=Decimal(str(round(o, 4))),
        high=Decimal(str(round(h, 4))),
        low=Decimal(str(round(l, 4))),
        close=Decimal(str(round(c, 4))),
        volume=Decimal(str(v)),
    )


def build_trend_series(n_flat=65, n_ramp_up=15, n_ramp_down=25, ramp_up_step=0.5, ramp_down_step=0.6):
    """نوسان تخت -> رمپ صعودی (کراس صعودی EMA9/21 با تاییدیهٔ حجم) -> رمپ نزولی
    (کراس نزولی، برای تست should_exit). n_flat=65 (نه ۴۰) تا موقع کراس واقعیِ
    شروع رمپ (idx=65) حداقل ۵۰ کندل برای مقدار معتبر EMA_50 وجود داشته باشه."""
    candles = []
    price = 100.0
    ts = 1_700_000_000
    for i in range(n_flat):
        p = 100.0 + 0.3 * math.sin(i / 2)
        candles.append(_candle(ts, price, max(price, p) + 0.2, min(price, p) - 0.2, p, 100))
        price = p
        ts += 3600
    for _ in range(n_ramp_up):
        c = price + ramp_up_step
        candles.append(_candle(ts, price, max(price, c) + 0.2, min(price, c) - 0.2, c, 500))
        price = c
        ts += 3600
    for _ in range(n_ramp_down):
        c = price - ramp_down_step
        candles.append(_candle(ts, price, max(price, c) + 0.2, min(price, c) - 0.2, c, 300))
        price = c
        ts += 3600
    return candles


def build_downtrend_bounce_series(n_decline=70, decline_step=0.5, n_bounce=10, bounce_step=1.5):
    """روند نزولی بلندمدت (EMA50 هم زیر قیمت‌های قبلی و هم رو به پایین) + یک
    جهش کوتاه‌مدت که EMA9 رو از EMA21 رد می‌کنه (کراس صعودی + RSI/حجم قبول‌شدنی)
    ولی close هنوز زیر EMA50 مونده — یعنی هنوز واقعاً برنگشته به روند صعودی،
    فقط یه جهشِ داخل روند نزولیه. برای تست فیلتر EMA50 (باید این کراس رد بشه)."""
    candles = []
    price = 150.0
    ts = 1_700_000_000
    for _ in range(n_decline):
        c = price - decline_step
        candles.append(_candle(ts, price, max(price, c) + 0.2, min(price, c) - 0.2, c, 200))
        price = c
        ts += 3600
    for _ in range(n_bounce):
        c = price + bounce_step
        candles.append(_candle(ts, price, max(price, c) + 0.2, min(price, c) - 0.2, c, 600))
        price = c
        ts += 3600
    return candles


def build_mean_reversion_series(n_stable=30, n_drop=8, drop_step=1.5):
    candles = []
    price = 100.0
    ts = 1_700_000_000
    for i in range(n_stable):
        p = 100.0 + 0.5 * math.sin(i / 2)
        candles.append(_candle(ts, price, max(price, p) + 0.2, min(price, p) - 0.2, p, 100))
        price = p
        ts += 3600
    for _ in range(n_drop):
        c = price - drop_step
        candles.append(_candle(ts, price, max(price, c) + 0.1, min(price, c) - 0.1, c, 100))
        price = c
        ts += 3600
    return candles


def build_breakout_series(n_range=35, breakout_jump=6.0, breakout_volume=800):
    candles = []
    price = 100.0
    ts = 1_700_000_000
    for i in range(n_range):
        p = 100.0 + 1.5 * math.sin(i / 3)
        candles.append(_candle(ts, price, max(price, p) + 0.3, min(price, p) - 0.3, p, 100))
        price = p
        ts += 3600
    c = price + breakout_jump
    candles.append(_candle(ts, price, c + 0.3, price - 0.2, c, breakout_volume))
    return candles


# ---------------------------------------------------------------------------
# Trend + Momentum + Volume
# ---------------------------------------------------------------------------

def test_trend_strategy_fades_bullish_cross_with_sell_signal():
    """استراتژی معکوس شده (fade) — کراس صعودی EMA9/21 با تاییدیهٔ RSI/حجم/EMA50
    حالا سیگنال فروش تولید می‌کنه، نه خرید (طبق شواهد تست edge)."""
    candles = build_trend_series()
    df = compute_indicators(candles_to_dataframe(candles))
    strategy = TrendMomentumVolumeStrategy()

    # اسلایس دقیقاً تا کندل کراس صعودی واقعی (index 65 — شروع رمپ، close بالای EMA50)
    signal = strategy.generate_entry_signal(df.iloc[:66], "BTCIRT")

    assert signal is not None
    assert signal.direction == "sell"
    assert signal.take_profit < signal.entry_price_hint < signal.stop_loss
    assert signal.strategy_name == "trend_momentum_volume"


def test_trend_strategy_no_signal_without_crossover():
    candles = build_trend_series()
    df = compute_indicators(candles_to_dataframe(candles))
    strategy = TrendMomentumVolumeStrategy()

    # قبل از این‌که اصلاً کراسی اتفاق بیفته
    signal = strategy.generate_entry_signal(df.iloc[:20], "BTCIRT")

    assert signal is None


def test_trend_strategy_filters_cross_against_ema50_trend():
    """کراس صعودی EMA9/21 با RSI/حجم قابل‌قبول ولی close هنوز زیر EMA50 —
    یعنی فقط یه جهش کوتاه‌مدت داخل یه روند نزولی بزرگ‌تره، نه شروع واقعی
    روند صعودی. باید رد بشه (بدون فیلتر EMA50 قبلاً سیگنال تولید می‌شد)."""
    candles = build_downtrend_bounce_series()
    df = compute_indicators(candles_to_dataframe(candles))
    strategy = TrendMomentumVolumeStrategy()

    signal = strategy.generate_entry_signal(df.iloc[:77], "BTCIRT")

    assert signal is None


def test_trend_strategy_never_manual_exits():
    """مثل breakout_atr، این استراتژی هم صرفاً به OCO نیتیو متکیه — تست edge
    بدون هیچ خروج دستی انجام شده بود، پس قانون خروج تازه‌ای اضافه نکردیم."""
    candles = build_trend_series()
    df = compute_indicators(candles_to_dataframe(candles))
    strategy = TrendMomentumVolumeStrategy()

    should_exit, reason = strategy.should_exit(df.iloc[:89], position_direction="buy")

    assert should_exit is False
    assert "OCO" in reason


# ---------------------------------------------------------------------------
# Mean Reversion + RSI + Bollinger Bands
# ---------------------------------------------------------------------------

def test_mean_reversion_generates_buy_signal_when_oversold():
    candles = build_mean_reversion_series()
    df = compute_indicators(candles_to_dataframe(candles))
    strategy = MeanReversionStrategy()

    signal = strategy.generate_entry_signal(df, "ETHIRT")

    assert signal is not None
    assert signal.direction == "buy"
    assert signal.take_profit > signal.entry_price_hint  # هدف باند مقابل بالاتره
    assert signal.stop_loss < signal.entry_price_hint
    bbm = Decimal(str(df.iloc[-1]["BBM_20_2.0"]))
    assert signal.take_profit > bbm  # هدف باید فراتر از باند میانی باشه (نه خودِ میانی)


def test_mean_reversion_no_signal_in_stable_range():
    candles = build_mean_reversion_series(n_drop=0)
    df = compute_indicators(candles_to_dataframe(candles))
    strategy = MeanReversionStrategy()

    signal = strategy.generate_entry_signal(df, "ETHIRT")

    assert signal is None


def test_mean_reversion_should_exit_always_false():
    candles = build_mean_reversion_series()
    df = compute_indicators(candles_to_dataframe(candles))
    strategy = MeanReversionStrategy()

    should_exit, _ = strategy.should_exit(df, position_direction="sell")

    assert should_exit is False


# ---------------------------------------------------------------------------
# Breakout + ATR
# ---------------------------------------------------------------------------

def test_breakout_strategy_fades_channel_breakout_with_sell_signal():
    """استراتژی معکوس شده (fade) — شکست سقف کانال حالا سیگنال فروش تولید
    می‌کنه، نه خرید (طبق شواهد تست edge)."""
    candles = build_breakout_series()
    df = compute_indicators(candles_to_dataframe(candles))
    strategy = BreakoutATRStrategy()

    signal = strategy.generate_entry_signal(df, "DOGEIRT")

    assert signal is not None
    assert signal.direction == "sell"
    assert signal.native_order_hint == "oco"


def test_breakout_strategy_filters_marginal_breakout_within_buffer():
    """close فقط کمی بالاتر از channel_high (نه به‌اندازهٔ ۰.۲۵ ATR) — قبلاً
    (بدون بافر تاییدیه) سیگنال تولید می‌شد؛ الان باید رد بشه چون شکست
    قاطع نیست، فقط لمسِ مرزیه (شایع‌ترین حالت شکست کاذب)."""
    candles = build_breakout_series(breakout_jump=3.3)
    df = compute_indicators(candles_to_dataframe(candles))
    strategy = BreakoutATRStrategy()

    signal = strategy.generate_entry_signal(df, "DOGEIRT")

    assert signal is None


def test_breakout_strategy_filters_weak_volume_breakout():
    """شکست قاطع (فراتر از بافر) ولی حجم فقط کمی بالاتر از میانگین (نه ۱.۵
    برابر) — قبلاً سیگنال تولید می‌شد؛ الان باید رد بشه چون تاییدیهٔ حجمی
    قوی نیست."""
    candles = build_breakout_series(breakout_jump=6.0, breakout_volume=150)
    df = compute_indicators(candles_to_dataframe(candles))
    strategy = BreakoutATRStrategy()

    signal = strategy.generate_entry_signal(df, "DOGEIRT")

    assert signal is None


def test_breakout_strategy_no_signal_inside_range():
    candles = build_breakout_series(breakout_jump=0.0)
    df = compute_indicators(candles_to_dataframe(candles))
    strategy = BreakoutATRStrategy()

    signal = strategy.generate_entry_signal(df, "DOGEIRT")

    assert signal is None


def test_breakout_strategy_never_manual_exits():
    candles = build_breakout_series()
    df = compute_indicators(candles_to_dataframe(candles))
    strategy = BreakoutATRStrategy()

    should_exit, reason = strategy.should_exit(df, position_direction="buy")

    assert should_exit is False
    assert "OCO" in reason


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_registry_lists_all_three_strategies():
    names = list_strategies()
    assert set(names) == {"trend_momentum_volume", "mean_reversion_rsi_bb", "breakout_atr"}


def test_registry_get_strategy_returns_correct_instance():
    strategy = get_strategy("breakout_atr")
    assert isinstance(strategy, BreakoutATRStrategy)


def test_registry_unknown_strategy_raises():
    try:
        get_strategy("does_not_exist")
        assert False, "باید ValueError بندازه"
    except ValueError:
        pass
