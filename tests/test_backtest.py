from decimal import Decimal

from nobitex_bot.analysis.indicators import candles_to_dataframe
from nobitex_bot.backtest.engine import BacktestConfig, BacktestEngine
from nobitex_bot.backtest.metrics import TradeResult, compute_max_drawdown_pct, compute_win_rate
from nobitex_bot.backtest.report import BacktestResult, aggregate_by_strategy, pick_best_strategy
from nobitex_bot.backtest.metrics import BacktestMetrics
from nobitex_bot.strategies.trend_momentum_volume import TrendMomentumVolumeStrategy
from tests.test_strategies import build_trend_series


def test_engine_executes_entry_at_next_candle_open_not_signal_candle_close():
    """جلوگیری از look-ahead bias: قیمت ورود باید open کندل *بعد از* سیگنال باشه."""
    candles = build_trend_series()
    df = candles_to_dataframe(candles)
    engine = BacktestEngine(BacktestConfig(initial_capital=Decimal("10000000")))

    result = engine.run("BTCIRT", "60", candles, TrendMomentumVolumeStrategy())

    assert len(result.trades) >= 1
    first_trade = result.trades[0]
    # کندلی که entry_time داره باید همون open رو به‌عنوان entry_price داشته باشه (نه close کندل قبلی)
    matching_candle = df[df["timestamp"] == first_trade.entry_time].iloc[0]
    assert first_trade.entry_price == Decimal(str(matching_candle["open"]))


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
