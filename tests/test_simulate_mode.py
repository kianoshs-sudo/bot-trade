from decimal import Decimal
from unittest.mock import MagicMock

from nobitex_bot.paper_trading.runner import PaperTradingRunner, StrategyTrack
from nobitex_bot.risk.risk_manager import RiskConfig, RiskManager
from nobitex_bot.strategies.trend_momentum_volume import TrendMomentumVolumeStrategy
from tests.test_paper_trading import AlwaysApprove, make_settings
from tests.test_strategies import build_trend_series


def _runner(tmp_path, simulate, order_fails=True):
    from nobitex_bot.data.storage import Storage

    storage = Storage(tmp_path / "sim.sqlite")
    market_data = MagicMock()
    market_data.get_ohlc_history.return_value = build_trend_series()[:66]
    stat = MagicMock()
    stat.latest = Decimal("100.68")
    market_data.get_all_market_stats.return_value = {"BTCIRT": stat}

    scanner = MagicMock()
    opportunity = MagicMock()
    opportunity.symbol = "BTCIRT"
    scanner.scan.return_value = [opportunity]

    order_executor = MagicMock()
    if order_fails:
        order_executor.submit_order.side_effect = RuntimeError("HTTP401: API key is invalid.")

    track = StrategyTrack(
        strategy=TrendMomentumVolumeStrategy(), resolution="60",
        capital=Decimal("50000000"), risk_manager=RiskManager(RiskConfig()),
    )
    runner = PaperTradingRunner(
        settings=make_settings(tmp_path), market_data=market_data, scanner=scanner,
        tracks=[track], order_executor=order_executor, storage=storage,
        approval_gate=AlwaysApprove(), simulate=simulate,
    )
    return runner, storage, order_executor, track


def test_simulate_records_the_trade_without_touching_the_exchange(tmp_path):
    """هدف «ببینم سرمایه روی این سیگنال‌ها چه می‌شود» به صرافی نیازی ندارد، ولی
    ثبت معاملهٔ کاغذی به موفقیت سفارش گره خورده بود: در دادهٔ زنده هر ۶۷ سفارش
    با HTTP401 رد شد و چون ``submit_order`` قبل از ``open_paper_trade`` صدا
    زده می‌شود، هیچ معامله‌ای — حتی مجازی — ثبت نشد."""
    runner, storage, order_executor, track = _runner(tmp_path, simulate=True)

    runner.run_once()

    order_executor.submit_order.assert_not_called()
    assert "BTCIRT" in track.open_positions
    assert len(storage.get_open_paper_trades()) == 1
    storage.close()


def test_without_simulate_a_failing_exchange_still_blocks_everything(tmp_path):
    """رفتار پیش‌فرض عوض نمی‌شود — حالت شبیه‌سازی باید صریح درخواست شود."""
    runner, storage, order_executor, track = _runner(tmp_path, simulate=False)

    runner.run_once()

    order_executor.submit_order.assert_called()
    assert "BTCIRT" not in track.open_positions
    assert storage.get_open_paper_trades() == []
    storage.close()


def test_simulated_trade_closes_and_moves_capital(tmp_path):
    """منحنی سرمایه فقط وقتی معنا دارد که معامله‌ها بسته شوند و PnL روی سرمایه
    اعمال شود."""
    runner, storage, _, track = _runner(tmp_path, simulate=True)
    runner.run_once()
    opened = track.open_positions["BTCIRT"]
    capital_before = track.capital

    runner._close_position(track, opened, opened.take_profit, "تست برخورد حد سود")

    assert track.capital != capital_before
    closed = storage.get_closed_paper_trades()
    assert len(closed) == 1 and closed[0]["pnl"] is not None
    storage.close()
