from datetime import datetime, timedelta, timezone
from decimal import Decimal

from nobitex_bot.risk.position_sizing import calculate_position_size
from nobitex_bot.risk.risk_manager import RiskConfig, RiskManager
from nobitex_bot.strategies.base import TradeSignal


def make_signal(entry=100, stop_loss=95, take_profit=110, symbol="BTCIRT", direction="buy"):
    return TradeSignal(
        symbol=symbol,
        direction=direction,
        entry_price_hint=Decimal(str(entry)),
        stop_loss=Decimal(str(stop_loss)),
        take_profit=Decimal(str(take_profit)),
        reason="test",
        strategy_name="test_strategy",
    )


def test_calculate_position_size_basic():
    size = calculate_position_size(
        capital=Decimal("10000000"), risk_pct=Decimal("0.02"), entry_price=Decimal("100"), stop_loss=Decimal("95")
    )
    # ریسک مبلغی = ۲۰۰,۰۰۰ ؛ فاصلهٔ SL = ۵ ؛ واحد = ۴۰,۰۰۰ ؛ notional = ۴,۰۰۰,۰۰۰
    assert size == Decimal("4000000")


def test_calculate_position_size_zero_when_no_price_risk():
    assert calculate_position_size(Decimal("1000"), Decimal("0.02"), Decimal("100"), Decimal("100")) == Decimal("0")


def test_evaluate_approves_valid_signal():
    rm = RiskManager(RiskConfig(risk_per_trade_pct=Decimal("0.02")))
    signal = make_signal(entry=100, stop_loss=95, symbol="BTCIRT")

    decision = rm.evaluate(signal, capital=Decimal("10000000"), market_price=Decimal("100"), open_trades_count=0)

    assert decision.approved is True
    assert decision.position_size_quote == Decimal("4000000")


def test_evaluate_rejects_when_max_concurrent_trades_reached():
    rm = RiskManager(RiskConfig(max_concurrent_trades=2))
    signal = make_signal()

    decision = rm.evaluate(signal, capital=Decimal("10000000"), market_price=Decimal("100"), open_trades_count=2)

    assert decision.approved is False
    assert "هم‌زمان" in decision.reason


def test_evaluate_rejects_on_bad_price_deviation():
    rm = RiskManager(RiskConfig())
    signal = make_signal(entry=150)  # قیمت پیشنهادی خیلی بالاتر از بازار

    decision = rm.evaluate(signal, capital=Decimal("10000000"), market_price=Decimal("100"), open_trades_count=0)

    assert decision.approved is False
    assert "BadPrice" in decision.reason


def test_evaluate_rejects_small_order_below_min_value():
    rm = RiskManager(RiskConfig(risk_per_trade_pct=Decimal("0.02")))
    signal = make_signal(entry=100, stop_loss=95, symbol="BTCIRT")

    decision = rm.evaluate(signal, capital=Decimal("1000"), market_price=Decimal("100"), open_trades_count=0)

    assert decision.approved is False
    assert "SmallOrder" in decision.reason


def test_daily_loss_limit_halts_trading():
    rm = RiskManager(RiskConfig(max_daily_loss_pct=Decimal("0.05")))
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    capital = Decimal("10000000")

    rm.record_closed_trade(Decimal("-600000"), now=now)  # ۶٪ ضرر > حد ۵٪

    assert rm.is_daily_loss_limit_hit(capital, now=now) is True

    signal = make_signal()
    decision = rm.evaluate(signal, capital=capital, market_price=Decimal("100"), open_trades_count=0, now=now)
    assert decision.approved is False
    assert "ضرر روزانه" in decision.reason


def test_daily_loss_limit_resets_next_day():
    rm = RiskManager(RiskConfig(max_daily_loss_pct=Decimal("0.05")))
    day1 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    day2 = day1 + timedelta(days=1)
    capital = Decimal("10000000")

    rm.record_closed_trade(Decimal("-600000"), now=day1)
    assert rm.is_daily_loss_limit_hit(capital, now=day1) is True

    assert rm.is_daily_loss_limit_hit(capital, now=day2) is False


def test_profitable_day_does_not_halt_trading():
    rm = RiskManager(RiskConfig(max_daily_loss_pct=Decimal("0.05")))
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    capital = Decimal("10000000")

    rm.record_closed_trade(Decimal("500000"), now=now)

    assert rm.is_daily_loss_limit_hit(capital, now=now) is False
