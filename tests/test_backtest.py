from decimal import Decimal

import pandas as pd

from nobitex_bot.analysis.indicators import candles_to_dataframe
from nobitex_bot.backtest.engine import BacktestConfig, BacktestEngine
from nobitex_bot.backtest.metrics import TradeResult, compute_max_drawdown_pct, compute_win_rate
from nobitex_bot.backtest.report import BacktestResult, aggregate_by_strategy, pick_best_strategy
from nobitex_bot.backtest.metrics import BacktestMetrics
from nobitex_bot.strategies.trend_momentum_volume import TrendMomentumVolumeStrategy
from tests.test_strategies import build_trend_series


class _NoExitStrategy:
    def should_exit(self, window, direction):
        return False, ""


def test_engine_executes_entry_at_next_candle_open_not_signal_candle_close():
    """جلوگیری از look-ahead bias: قیمت ورود باید open کندل *بعد از* سیگنال باشه
    (اسپرد/اسلیپیج عمداً صفر شده تا این تست فقط زمان‌بندی رو بسنجه، نه هزینه)."""
    candles = build_trend_series()
    df = candles_to_dataframe(candles)
    engine = BacktestEngine(
        BacktestConfig(initial_capital=Decimal("10000000"), spread_pct=Decimal("0"), slippage_pct=Decimal("0"))
    )

    result = engine.run("BTCIRT", "60", candles, TrendMomentumVolumeStrategy())

    assert len(result.trades) >= 1
    first_trade = result.trades[0]
    # کندلی که entry_time داره باید همون open رو به‌عنوان entry_price داشته باشه (نه close کندل قبلی)
    matching_candle = df[df["timestamp"] == first_trade.entry_time].iloc[0]
    assert first_trade.entry_price == Decimal(str(matching_candle["open"]))


def test_engine_applies_execution_cost_to_entry_price():
    """اسپرد/اسلیپیج باید قیمت ورود رو به ضرر معامله‌گر بدتر کنه — بدون این،
    بک‌تست فرض می‌کرد می‌شه دقیقاً روی قیمت خام کندل معامله کرد."""
    candles = build_trend_series()
    df = candles_to_dataframe(candles)
    engine = BacktestEngine(
        BacktestConfig(initial_capital=Decimal("10000000"), spread_pct=Decimal("0.002"), slippage_pct=Decimal("0.001"))
    )

    result = engine.run("BTCIRT", "60", candles, TrendMomentumVolumeStrategy())

    assert len(result.trades) >= 1
    first_trade = result.trades[0]
    matching_candle = df[df["timestamp"] == first_trade.entry_time].iloc[0]
    raw_open = Decimal(str(matching_candle["open"]))
    # این استراتژی الان fade هست (کراس صعودی -> sell)، پس هزینهٔ اجرا به ضرر فروشنده اعمال می‌شه
    assert first_trade.direction == "sell"
    expected_entry = raw_open * Decimal("0.998")  # sell: spread/2 (0.001) + slippage (0.001) به ضرر فروشنده
    assert first_trade.entry_price == expected_entry


def test_apply_execution_cost_pushes_price_up_when_buying():
    engine = BacktestEngine(BacktestConfig(spread_pct=Decimal("0.002"), slippage_pct=Decimal("0.001")))
    assert engine._apply_execution_cost(Decimal("100"), is_buying=True) == Decimal("100.2")


def test_apply_execution_cost_pushes_price_down_when_selling():
    engine = BacktestEngine(BacktestConfig(spread_pct=Decimal("0.002"), slippage_pct=Decimal("0.001")))
    assert engine._apply_execution_cost(Decimal("100"), is_buying=False) == Decimal("99.8")


def test_check_exit_applies_execution_cost_on_stop_loss_hit():
    engine = BacktestEngine(BacktestConfig(spread_pct=Decimal("0.002"), slippage_pct=Decimal("0.001")))
    position = {"direction": "buy", "stop_loss": Decimal("95"), "take_profit": Decimal("110")}
    candle = pd.Series({"low": 94.0, "high": 96.0, "open": 95.5})

    exit_price, reason = engine._check_exit(position, candle, pd.DataFrame(), _NoExitStrategy())

    # بستن پوزیشن buy یعنی فروش -> قیمت به ضرر معامله‌گر پایین‌تر می‌ره
    assert exit_price == Decimal("95") * Decimal("0.998")
    assert "Stop Loss" in reason


def test_check_exit_does_not_apply_execution_cost_on_take_profit_hit():
    """TP یه سفارش limit از‌قبل‌نشسته‌ست — باید دقیقاً همون قیمت خام اجرا بشه،
    بدون اسپرد/اسلیپیج اضافه."""
    engine = BacktestEngine(BacktestConfig(spread_pct=Decimal("0.002"), slippage_pct=Decimal("0.001")))
    position = {"direction": "buy", "stop_loss": Decimal("95"), "take_profit": Decimal("110")}
    candle = pd.Series({"low": 105.0, "high": 111.0, "open": 106.0})

    exit_price, reason = engine._check_exit(position, candle, pd.DataFrame(), _NoExitStrategy())

    assert exit_price == Decimal("110")
    assert "Take Profit" in reason


def test_engine_applies_fees_to_pnl():
    candles = build_trend_series()
    engine = BacktestEngine(BacktestConfig(initial_capital=Decimal("10000000"), fee_rate=Decimal("0.01")))

    result = engine.run("BTCIRT", "60", candles, TrendMomentumVolumeStrategy())

    assert len(result.trades) >= 1
    trade = result.trades[0]
    expected_fee = trade.size_quote * Decimal("0.01") * 2
    assert trade.fee_paid == expected_fee


def test_engine_skips_signal_below_min_order_value():
    candles = build_trend_series()
    # سرمایهٔ خیلی کم -> اندازهٔ پوزیشن ریسک-محور همیشه زیر حداقل ارزش معامله می‌مونه
    engine = BacktestEngine(BacktestConfig(initial_capital=Decimal("1000")))

    result = engine.run("BTCIRT", "60", candles, TrendMomentumVolumeStrategy())

    assert len(result.trades) == 0
    assert result.skipped_small_order_signals >= 1


def test_metrics_win_rate_and_drawdown():
    trades = [TradeResult(pnl=100), TradeResult(pnl=-50), TradeResult(pnl=200)]
    assert compute_win_rate(trades) == 2 / 3

    equity_curve = [1000, 1200, 900, 1500]
    # peak 1200 -> افت به 900 یعنی ۲۵٪ افت
    assert compute_max_drawdown_pct(equity_curve) == (1200 - 900) / 1200


def test_aggregate_and_pick_best_strategy_by_sharpe():
    good = BacktestResult(
        symbol="BTCIRT",
        strategy_name="strategy_a",
        metrics=BacktestMetrics(total_trades=5, win_rate=0.6, net_pnl=100, net_pnl_pct=0.1, max_drawdown_pct=0.05, sharpe_ratio=2.0),
        final_capital=Decimal("11000"),
    )
    bad = BacktestResult(
        symbol="BTCIRT",
        strategy_name="strategy_b",
        metrics=BacktestMetrics(total_trades=5, win_rate=0.4, net_pnl=-50, net_pnl_pct=-0.05, max_drawdown_pct=0.3, sharpe_ratio=-0.5),
        final_capital=Decimal("9500"),
    )

    aggregated = aggregate_by_strategy([good, bad])

    assert pick_best_strategy(aggregated) == "strategy_a"
