from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from nobitex_bot.config import Settings
from nobitex_bot.paper_trading.approval import ApprovalGate
from nobitex_bot.paper_trading.runner import OpenPosition, PaperTradingRunner, StrategyTrack
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


def make_runner(tmp_path, approval_gate, candles, latest_price="100.68", resolution="60"):
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

    track = StrategyTrack(
        strategy=TrendMomentumVolumeStrategy(),
        resolution=resolution,
        capital=Decimal("10000000"),
        risk_manager=RiskManager(RiskConfig(risk_per_trade_pct=Decimal("0.02"))),
    )

    runner = PaperTradingRunner(
        settings=settings,
        market_data=market_data,
        scanner=scanner,
        tracks=[track],
        order_executor=order_executor,
        storage=storage,
        approval_gate=approval_gate,
    )
    return runner, storage, order_executor, track


def test_runner_rejects_production_env(tmp_path):
    from nobitex_bot.data.storage import Storage

    settings = make_settings(tmp_path, env="production")
    storage = Storage(tmp_path / "test.sqlite")
    track = StrategyTrack(strategy=TrendMomentumVolumeStrategy(), resolution="60", capital=Decimal("1000000"))

    with pytest.raises(RuntimeError):
        PaperTradingRunner(
            settings=settings,
            market_data=MagicMock(),
            scanner=MagicMock(),
            tracks=[track],
            order_executor=MagicMock(),
            storage=storage,
            approval_gate=AlwaysApprove(),
        )
    storage.close()


def test_run_once_opens_position_when_signal_and_approval_pass(tmp_path):
    candles = build_trend_series()[:41]  # دقیقاً تا کندل کراس صعودی
    runner, storage, order_executor, track = make_runner(tmp_path, AlwaysApprove(), candles)

    runner.run_once()

    assert "BTCIRT" in track.open_positions
    assert order_executor.submit_order.call_count == 2  # ورود + OCO خروج
    open_trades = storage.get_open_paper_trades()
    assert len(open_trades) == 1
    assert open_trades[0]["resolution"] == "60"
    storage.close()


def test_run_once_does_not_open_position_when_user_rejects(tmp_path):
    candles = build_trend_series()[:41]
    runner, storage, order_executor, track = make_runner(tmp_path, AlwaysReject(), candles)

    runner.run_once()

    assert "BTCIRT" not in track.open_positions
    order_executor.submit_order.assert_not_called()
    storage.close()


def test_check_exits_closes_position_on_stop_loss_hit(tmp_path):
    candles = build_trend_series()[:41]
    runner, storage, _, track = make_runner(tmp_path, AlwaysApprove(), candles, latest_price="90")

    trade_id = storage.open_paper_trade(
        "BTCIRT", "trend_momentum_volume", "60", "buy", 1_700_000_000, Decimal("100"), Decimal("1000000"), "test"
    )
    track.open_positions["BTCIRT"] = OpenPosition(
        trade_id=trade_id, symbol="BTCIRT", strategy_name="trend_momentum_volume", direction="buy",
        entry_price=Decimal("100"), stop_loss=Decimal("95"), take_profit=Decimal("120"), size_quote=Decimal("1000000"),
    )

    runner._check_exits(track)

    assert "BTCIRT" not in track.open_positions
    closed = storage.get_closed_paper_trades()
    assert len(closed) == 1
    assert closed[0]["exit_reason"].startswith("برخورد Stop Loss")
    storage.close()


def test_check_exits_keeps_position_when_price_between_sl_and_tp(tmp_path):
    candles = build_trend_series()[:41]
    runner, storage, _, track = make_runner(tmp_path, AlwaysApprove(), candles, latest_price="105")

    trade_id = storage.open_paper_trade(
        "BTCIRT", "trend_momentum_volume", "60", "buy", 1_700_000_000, Decimal("100"), Decimal("1000000"), "test"
    )
    track.open_positions["BTCIRT"] = OpenPosition(
        trade_id=trade_id, symbol="BTCIRT", strategy_name="trend_momentum_volume", direction="buy",
        entry_price=Decimal("100"), stop_loss=Decimal("95"), take_profit=Decimal("120"), size_quote=Decimal("1000000"),
    )

    runner._check_exits(track)

    assert "BTCIRT" in track.open_positions
    storage.close()


def test_multiple_tracks_run_independently_same_symbol(tmp_path):
    """دو ترکیب مستقل (همون استراتژی، دو تایم‌فریم متفاوت) باید بتونن هم‌زمان
    روی یک نماد پوزیشن باز کنن — چون هر track حساب/ریسک جدای خودشو داره."""
    from nobitex_bot.data.storage import Storage

    settings = make_settings(tmp_path)
    storage = Storage(tmp_path / "test.sqlite")
    candles = build_trend_series()[:41]

    market_data = MagicMock()
    market_data.get_ohlc_history.return_value = candles
    stat = MagicMock()
    stat.latest = Decimal("100.68")
    market_data.get_all_market_stats.return_value = {"BTCIRT": stat}

    scanner = MagicMock()
    scan_result = MagicMock()
    scan_result.symbol = "BTCIRT"
    scanner.scan.return_value = [scan_result]

    track_15m = StrategyTrack(strategy=TrendMomentumVolumeStrategy(), resolution="15", capital=Decimal("10000000"))
    track_4h = StrategyTrack(strategy=TrendMomentumVolumeStrategy(), resolution="240", capital=Decimal("10000000"))

    runner = PaperTradingRunner(
        settings=settings,
        market_data=market_data,
        scanner=scanner,
        tracks=[track_15m, track_4h],
        order_executor=MagicMock(),
        storage=storage,
        approval_gate=AlwaysApprove(),
    )

    runner.run_once()

    assert "BTCIRT" in track_15m.open_positions
    assert "BTCIRT" in track_4h.open_positions
    closed_or_open_resolutions = {t["resolution"] for t in storage.get_open_paper_trades()}
    assert closed_or_open_resolutions == {"15", "240"}
    storage.close()
