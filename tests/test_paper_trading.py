from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from nobitex_bot.config import Settings
from nobitex_bot.paper_trading.approval import ApprovalGate
from nobitex_bot.paper_trading.runner import OpenPosition, PaperTradingRunner
from nobitex_bot.risk.risk_manager import RiskConfig, RiskManager
from nobitex_bot.strategies.trend_momentum_volume import TrendMomentumVolumeStrategy
from tests.test_strategies import build_trend_series


class AlwaysApprove(ApprovalGate):
    def request_approval(self, signal, position_size_quote):
        return True


class AlwaysReject(ApprovalGate):
    def request_approval(self, signal, position_size_quote):
        return False


def make_settings(tmp_path, env="testnet"):
    return Settings(env=env, api_base_url="https://x", testnet_base_url="https://y", api_token="t", data_dir=tmp_path, log_level="INFO")


def make_runner(tmp_path, approval_gate, candles, latest_price="100.68"):
    from nobitex_bot.data.storage import Storage

    settings = make_settings(tmp_path)
    storage = Storage(tmp_path / "test.sqlite")

    market_data = MagicMock()
    market_data.get_ohlc_history.return_value = candles
    stat = MagicMock()
    stat.latest = Decimal(latest_price)
    market_data.get_all_market_stats.return_value = {"BTCIRT": stat}

    scanner = MagicMock()
    scan_result = MagicMock()
    scan_result.symbol = "BTCIRT"
    scanner.scan.return_value = [scan_result]

    order_executor = MagicMock()

    return PaperTradingRunner(
        settings=settings,
        market_data=market_data,
        scanner=scanner,
        strategies=[TrendMomentumVolumeStrategy()],
        risk_manager=RiskManager(RiskConfig(risk_per_trade_pct=Decimal("0.02"))),
        order_executor=order_executor,
        storage=storage,
        approval_gate=approval_gate,
        capital=Decimal("10000000"),
    ), storage, order_executor


def test_runner_rejects_production_env(tmp_path):
    from nobitex_bot.data.storage import Storage

    settings = make_settings(tmp_path, env="production")
    storage = Storage(tmp_path / "test.sqlite")

    with pytest.raises(RuntimeError):
        PaperTradingRunner(
            settings=settings,
            market_data=MagicMock(),
            scanner=MagicMock(),
            strategies=[],
            risk_manager=RiskManager(),
            order_executor=MagicMock(),
            storage=storage,
            approval_gate=AlwaysApprove(),
            capital=Decimal("1000000"),
        )
    storage.close()


def test_run_once_opens_position_when_signal_and_approval_pass(tmp_path):
    candles = build_trend_series()[:41]  # دقیقاً تا کندل کراس صعودی
    runner, storage, order_executor = make_runner(tmp_path, AlwaysApprove(), candles)

    runner.run_once()

    assert "BTCIRT" in runner.open_positions
    assert order_executor.submit_order.call_count == 2  # ورود + OCO خروج
    open_trades = storage.get_open_paper_trades()
    assert len(open_trades) == 1
    storage.close()


def test_run_once_does_not_open_position_when_user_rejects(tmp_path):
    candles = build_trend_series()[:41]
    runner, storage, order_executor = make_runner(tmp_path, AlwaysReject(), candles)

    runner.run_once()

    assert "BTCIRT" not in runner.open_positions
    order_executor.submit_order.assert_not_called()
    storage.close()


def test_check_exits_closes_position_on_stop_loss_hit(tmp_path):
    candles = build_trend_series()[:41]
    runner, storage, _ = make_runner(tmp_path, AlwaysApprove(), candles, latest_price="90")

    trade_id = storage.open_paper_trade("BTCIRT", "trend_momentum_volume", "buy", 1_700_000_000, Decimal("100"), Decimal("1000000"), "test")
    runner.open_positions["BTCIRT"] = OpenPosition(
        trade_id=trade_id, symbol="BTCIRT", strategy_name="trend_momentum_volume", direction="buy",
        entry_price=Decimal("100"), stop_loss=Decimal("95"), take_profit=Decimal("120"), size_quote=Decimal("1000000"),
    )

    runner._check_exits()

    assert "BTCIRT" not in runner.open_positions
    closed = storage.get_closed_paper_trades()
    assert len(closed) == 1
    assert closed[0]["exit_reason"].startswith("برخورد Stop Loss")
    storage.close()


def test_check_exits_keeps_position_when_price_between_sl_and_tp(tmp_path):
    candles = build_trend_series()[:41]
    runner, storage, _ = make_runner(tmp_path, AlwaysApprove(), candles, latest_price="105")

    trade_id = storage.open_paper_trade("BTCIRT", "trend_momentum_volume", "buy", 1_700_000_000, Decimal("100"), Decimal("1000000"), "test")
    runner.open_positions["BTCIRT"] = OpenPosition(
        trade_id=trade_id, symbol="BTCIRT", strategy_name="trend_momentum_volume", direction="buy",
        entry_price=Decimal("100"), stop_loss=Decimal("95"), take_profit=Decimal("120"), size_quote=Decimal("1000000"),
    )

    runner._check_exits()

    assert "BTCIRT" in runner.open_positions
    storage.close()
