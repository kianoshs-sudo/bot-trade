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


def build_trend_series(n_flat=40, n_ramp_up=15, n_ramp_down=20, ramp_up_step=0.5, ramp_down_step=0.6):
    """نوسان تخت -> رمپ صعودی (کراس صعودی EMA9/21 با تاییدیهٔ حجم) -> رمپ نزولی
    (کراس نزولی، برای تست should_exit)."""
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


def build_breakout_series(n_range=35, breakout_jump=6.0):
    candles = []
    price = 100.0
    ts = 1_700_000_000
    for i in range(n_range):
        p = 100.0 + 1.5 * math.sin(i / 3)
        candles.append(_candle(ts, price, max(price, p) + 0.3, min(price, p) - 0.3, p, 100))
        price = p
        ts += 3600
    c = price + breakout_jump
    candles.append(_candle(ts, price, c + 0.3, price - 0.2, c, 800))
    return candles


# ---------------------------------------------------------------------------
# Trend + Momentum + Volume
# ---------------------------------------------------------------------------

def test_trend_strategy_generates_buy_signal_on_bullish_cross_with_volume():
    candles = build_trend_series()
    df = compute_indicators(candles_to_dataframe(candles))
    strategy = TrendMomentumVolumeStrategy()

    # اسلایس دقیقاً تا کندل کراس صعودی (index 40)
    signal = strategy.generate_entry_signal(df.iloc[:41], "BTCIRT")

    assert signal is not None
    assert signal.direction == "buy"
    assert signal.stop_loss < signal.entry_price_hint < signal.take_profit
    assert signal.strategy_name == "trend_momentum_volume"


def test_trend_strategy_no_signal_without_crossover():
    candles = build_trend_series()
    df = compute_indicators(candles_to_dataframe(candles))
    strategy = TrendMomentumVolumeStrategy()

    # قبل از این‌که اصلاً کراسی اتفاق بیفته
    signal = strategy.generate_entry_signal(df.iloc[:20], "BTCIRT")

    assert signal is None


def test_trend_strategy_should_exit_on_bearish_cross():
    candles = build_trend_series()
    df = compute_indicators(candles_to_dataframe(candles))
    strategy = TrendMomentumVolumeStrategy()

    should_exit, reason = strategy.should_exit(df.iloc[:64], position_direction="buy")

    assert should_exit is True
    assert "EMA" in reason


def test_trend_strategy_no_exit_mid_trend():
    candles = build_trend_series()
    df = compute_indicators(candles_to_dataframe(candles))
    strategy = TrendMomentumVolumeStrategy()

    should_exit, _ = strategy.should_exit(df.iloc[:50], position_direction="buy")

    assert should_exit is False


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
    assert signal.take_profit > signal.entry_price_hint  # هدف بازگشت به میانگین بالاتره
    assert signal.stop_loss < signal.entry_price_hint


def test_mean_reversion_no_signal_in_stable_range():
    candles = build_mean_reversion_series(n_drop=0)
    df = compute_indicators(candles_to_dataframe(candles))
    strategy = MeanReversionStrategy()

    signal = strategy.generate_entry_signal(df, "ETHIRT")

    assert signal is None


def test_mean_reversion_exit_at_middle_band():
    candles = build_mean_reversion_series()
    df = compute_indicators(candles_to_dataframe(candles))
    strategy = MeanReversionStrategy()

    should_exit, _ = strategy.should_exit(df, position_direction="sell")  # close << BBM پس sell باید خارج بشه

    assert should_exit is True


# ---------------------------------------------------------------------------
# Breakout + ATR
# ---------------------------------------------------------------------------

def test_breakout_strategy_generates_buy_signal_on_channel_breakout():
    candles = build_breakout_series()
    df = compute_indicators(candles_to_dataframe(candles))
    strategy = BreakoutATRStrategy()

    signal = strategy.generate_entry_signal(df, "DOGEIRT")

    assert signal is not None
    assert signal.direction == "buy"
    assert signal.native_order_hint == "oco"


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
