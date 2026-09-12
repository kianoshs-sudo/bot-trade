from decimal import Decimal

from nobitex_bot.monitoring.portfolio_stats import downsample, max_drawdown_pct, summarize, unrealized_pnl


def _closed(pnl, fee="1"):
    return {"pnl": pnl, "fee_paid": fee}


def test_summary_reports_more_than_win_rate():
    """یک برد ۳۰۰ و دو باخت ۱۰۰: وین‌ریت فقط ۳۳٪ است ولی سبد سودده است."""
    open_buy = {"symbol": "BTCIRT", "direction": "buy", "entry_price": "100", "size_quote": "1000"}

    s = summarize(
        Decimal("10000"),
        closed=[_closed("300"), _closed("-100"), _closed("-100")],
        open_trades=[open_buy],
        snapshots=[{"equity": "10000"}, {"equity": "10300"}, {"equity": "10100"}],
        prices={"BTCIRT": {"latest": "105", "bid": "110", "ask": "111"}},
    )

    assert s["win_rate"] == Decimal(1) / 3
    assert s["expectancy"] == Decimal("100") / 3
    assert s["profit_factor"] == Decimal("1.5")
    assert (s["capital"], s["unrealized"], s["equity"]) == (Decimal("10100"), Decimal("100"), Decimal("10200"))
    assert s["return_pct"] == Decimal("0.02")
    assert s["fees"] == Decimal("3")
    assert s["max_drawdown_pct"] == (Decimal("10300") - Decimal("10100")) / Decimal("10300")


def test_empty_portfolio_has_no_ratios_instead_of_fake_zeros():
    s = summarize(Decimal("10000"), closed=[], open_trades=[], snapshots=[], prices={})
    assert s["win_rate"] is None and s["profit_factor"] is None and s["expectancy"] is None
    assert s["equity"] == Decimal("10000") and s["return_pct"] == 0


def test_short_unrealized_uses_the_ask_it_would_buy_back_at():
    trade = {"symbol": "X", "direction": "sell", "entry_price": "100", "size_quote": "1000"}
    assert unrealized_pnl(trade, {"latest": "95", "bid": "94", "ask": "96"}) == Decimal("40")


def test_max_drawdown_is_measured_from_the_running_peak():
    assert max_drawdown_pct([Decimal(v) for v in ("100", "120", "90", "130")]) == Decimal("0.25")


def test_downsample_keeps_the_latest_point():
    points = list(range(1000))
    reduced = downsample(points, max_points=100)
    assert len(reduced) == 100 and reduced[-1] == 999 and reduced[0] == 0
