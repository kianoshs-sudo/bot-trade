from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from nobitex_bot.config import Settings
from nobitex_bot.paper_trading.approval import ApprovalGate
from nobitex_bot.paper_trading.runner import OpenPosition, PaperTradingRunner, StrategyTrack
from nobitex_bot.risk.risk_manager import RiskConfig, RiskManager
from nobitex_bot.strategies.trend_momentum_volume import TrendMomentumVolumeStrategy
from tests.test_strategies import _candle, build_trend_series


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
    candles = build_trend_series()[:66]  # دقیقاً تا کندل کراس صعودی
    runner, storage, order_executor, track = make_runner(tmp_path, AlwaysApprove(), candles)

    runner.run_once()

    assert "BTCIRT" in track.open_positions
    assert order_executor.submit_order.call_count == 2  # ورود + OCO خروج
    open_trades = storage.get_open_paper_trades()
    assert len(open_trades) == 1
    assert open_trades[0]["resolution"] == "60"
    storage.close()


def test_run_once_opens_position_with_raw_exchange_stats_symbol_format(tmp_path):
    """``market/stats`` واقعی نوبیتکس نمادها رو با فرمت خام (مثل ``btc-rls``)
    برمی‌گردونه، نه فرمت udf (``BTCIRT``) که بقیهٔ کد باهاش کار می‌کنه —
    برخلاف mock معمول این فایل که مستقیم با کلید ``BTCIRT`` ساخته می‌شه و
    این باگ رو پنهان می‌کنه. بدون تبدیل فرمت در ``_udf_keyed_market_stats``،
    ``symbol in stats`` همیشه False می‌شد و هیچ پوزیشنی هیچ‌وقت باز نمی‌شد."""
    candles = build_trend_series()[:66]
    runner, storage, order_executor, track = make_runner(tmp_path, AlwaysApprove(), candles)
    stat = MagicMock()
    stat.latest = Decimal("100.68")
    runner.market_data.get_all_market_stats.return_value = {"btc-rls": stat}

    runner.run_once()

    assert "BTCIRT" in track.open_positions
    assert order_executor.submit_order.call_count == 2
    storage.close()


def test_run_once_does_not_open_position_when_user_rejects(tmp_path):
    candles = build_trend_series()[:66]
    runner, storage, order_executor, track = make_runner(tmp_path, AlwaysReject(), candles)

    runner.run_once()

    assert "BTCIRT" not in track.open_positions
    order_executor.submit_order.assert_not_called()
    storage.close()


def test_check_exits_closes_position_on_stop_loss_hit(tmp_path):
    candles = build_trend_series()[:66]
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
    candles = build_trend_series()[:66]
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
    candles = build_trend_series()[:66]

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


def test_restore_state_rehydrates_open_position_so_exits_are_checked(tmp_path):
    """بازسازی حافظه — سناریوی واقعی GitHub Actions: چرخهٔ قبلی پوزیشن باز کرده،
    process تموم شده، و چرخهٔ جدید باید همون پوزیشن رو برای SL/TP چک کنه."""
    candles = build_trend_series()[:66]
    runner, storage, _, track = make_runner(tmp_path, AlwaysApprove(), candles, latest_price="90")

    # همون چیزی که چرخهٔ قبلی در دیتابیس نوشته (شامل SL/TP)
    storage.open_paper_trade(
        "BTCIRT", "trend_momentum_volume", "60", "buy", 1_700_000_000, Decimal("100"),
        Decimal("1000000"), "test", stop_loss=Decimal("95"), take_profit=Decimal("120"),
    )
    assert track.open_positions == {}, "حافظهٔ اجرای جدید باید از ابتدا خالی باشه"

    runner.restore_state()

    assert "BTCIRT" in track.open_positions
    position = track.open_positions["BTCIRT"]
    assert position.stop_loss == Decimal("95")
    assert position.take_profit == Decimal("120")

    # قیمت فعلی ۹۰ است — زیر حد ضرر ۹۵، پس باید بسته بشه
    runner._check_exits(track)
    assert "BTCIRT" not in track.open_positions
    closed = storage.get_closed_paper_trades()
    assert len(closed) == 1
    assert closed[0]["exit_reason"].startswith("برخورد Stop Loss")
    storage.close()


def test_restore_state_restores_capital_from_closed_trades(tmp_path):
    candles = build_trend_series()[:66]
    runner, storage, _, track = make_runner(tmp_path, AlwaysApprove(), candles)
    initial_capital = track.capital

    trade_id = storage.open_paper_trade(
        "BTCIRT", "trend_momentum_volume", "60", "buy", 1_700_000_000, Decimal("100"),
        Decimal("1000000"), "test", stop_loss=Decimal("95"), take_profit=Decimal("120"),
    )
    storage.close_paper_trade(
        trade_id, 1_700_003_600, Decimal("120"), Decimal("5000"), Decimal("195000"), "برخورد Take Profit (OCO)"
    )

    runner.restore_state()

    assert track.capital == initial_capital + Decimal("195000")
    assert track.open_positions == {}
    storage.close()


def test_restore_state_ignores_trades_from_other_strategy_track(tmp_path):
    candles = build_trend_series()[:66]
    runner, storage, _, track = make_runner(tmp_path, AlwaysApprove(), candles, resolution="60")

    # پوزیشن باز متعلق به تایم‌فریم دیگه‌ای که این اجرا فعال نیست
    storage.open_paper_trade(
        "BTCIRT", "trend_momentum_volume", "240", "buy", 1_700_000_000, Decimal("100"),
        Decimal("1000000"), "test", stop_loss=Decimal("95"), take_profit=Decimal("120"),
    )

    runner.restore_state()

    assert track.open_positions == {}, "پوزیشن تایم‌فریم دیگه نباید وارد این track بشه"
    assert len(storage.get_open_paper_trades()) == 1, "و نباید از دیتابیس هم حذف بشه"
    storage.close()


def test_restore_state_skips_legacy_position_without_sl_tp(tmp_path):
    """معامله‌های بازِ دیتابیس‌های قدیمی (بدون ستون SL/TP) نباید با قیمت اشتباه بسته بشن."""
    candles = build_trend_series()[:66]
    runner, storage, _, track = make_runner(tmp_path, AlwaysApprove(), candles, latest_price="90")

    storage.open_paper_trade(
        "BTCIRT", "trend_momentum_volume", "60", "buy", 1_700_000_000, Decimal("100"), Decimal("1000000"), "legacy"
    )

    runner.restore_state()

    assert track.open_positions == {}
    storage.close()


def test_open_position_persists_sl_tp_for_next_run(tmp_path):
    """چرخهٔ اول باید SL/TP رو ذخیره کنه وگرنه چرخهٔ بعدی نمی‌تونه بازسازی کنه."""
    candles = build_trend_series()[:66]
    runner, storage, _, _ = make_runner(tmp_path, AlwaysApprove(), candles)

    runner.run_once()

    open_trades = storage.get_open_paper_trades()
    assert len(open_trades) == 1
    assert open_trades[0]["stop_loss"] is not None
    assert open_trades[0]["take_profit"] is not None
    storage.close()


def test_two_consecutive_once_runs_share_state_end_to_end(tmp_path):
    """سناریوی کامل GitHub Actions: دو اجرای جدا با آبجکت‌های تازه ولی
    دیتابیس مشترک — اجرای دوم باید پوزیشن اجرای اول رو ببینه و ببنده."""
    from nobitex_bot.data.storage import Storage

    candles = build_trend_series()[:66]
    db_path = tmp_path / "shared.sqlite"

    def build_runner(latest_price):
        storage = Storage(db_path)
        market_data = MagicMock()
        market_data.get_ohlc_history.return_value = candles
        stat = MagicMock()
        stat.latest = Decimal(latest_price)
        market_data.get_all_market_stats.return_value = {"BTCIRT": stat}
        scanner = MagicMock()
        scan_result = MagicMock()
        scan_result.symbol = "BTCIRT"
        scanner.scan.return_value = [scan_result]
        track = StrategyTrack(
            strategy=TrendMomentumVolumeStrategy(), resolution="60", capital=Decimal("10000000"),
            risk_manager=RiskManager(RiskConfig(risk_per_trade_pct=Decimal("0.02"))),
        )
        runner = PaperTradingRunner(
            settings=make_settings(tmp_path), market_data=market_data, scanner=scanner, tracks=[track],
            order_executor=MagicMock(), storage=storage, approval_gate=AlwaysApprove(),
        )
        return runner, storage, track

    # اجرای اول — پوزیشن باز می‌شه
    runner1, storage1, track1 = build_runner("100.68")
    runner1.restore_state()
    runner1.run_once()
    assert "BTCIRT" in track1.open_positions
    entry = track1.open_positions["BTCIRT"]
    first_trade_id = entry.trade_id
    storage1.close()

    # اجرای دوم — process جدید، حافظهٔ in-memory خالی، قیمت به سمت حد ضرر رفته
    # (جهت SL بسته به direction فرق می‌کنه: برای sell، SL بالای قیمت ورودیه)
    if entry.direction == "buy":
        stop_loss_hit_price = str(entry.stop_loss - Decimal("1"))
    else:
        stop_loss_hit_price = str(entry.stop_loss + Decimal("1"))
    runner2, storage2, track2 = build_runner(stop_loss_hit_price)
    assert track2.open_positions == {}, "آبجکت جدید باید حافظهٔ خالی داشته باشه"

    runner2.restore_state()
    assert track2.open_positions["BTCIRT"].trade_id == first_trade_id, "پوزیشن اجرای قبلی باید بازسازی بشه"

    runner2.run_once()

    # معاملهٔ اجرای قبلی باید با برخورد حد ضرر بسته شده باشه — همون چیزی که
    # بدون restore_state هیچ‌وقت اتفاق نمی‌افتاد.
    closed = storage2.get_closed_paper_trades()
    assert [c["id"] for c in closed] == [first_trade_id]
    assert closed[0]["exit_reason"].startswith("برخورد Stop Loss")
    assert Decimal(closed[0]["pnl"]) < 0
    storage2.close()


def test_check_exits_closes_via_exchange_confirmation_even_when_price_is_between_sl_tp(tmp_path):
    """سناریوی دقیق نگرانی کاربر: قیمت بین دو چرخهٔ ۱۵ دقیقه‌ای به SL خورده و
    برگشته — روش قیمتی صرف این رو هرگز نمی‌بینه، ولی صرافی واقعاً اجرا کرده."""
    candles = build_trend_series()[:66]
    runner, storage, order_executor, track = make_runner(tmp_path, AlwaysApprove(), candles, latest_price="105")
    order_executor.client.get_order_status.return_value = {"order": {"id": 1, "status": "Done"}}

    trade_id = storage.open_paper_trade(
        "BTCIRT", "trend_momentum_volume", "60", "buy", 1_700_000_000, Decimal("100"), Decimal("1000000"), "test",
        stop_loss=Decimal("95"), take_profit=Decimal("120"), exit_client_order_id="exit-abc",
    )
    track.open_positions["BTCIRT"] = OpenPosition(
        trade_id=trade_id, symbol="BTCIRT", strategy_name="trend_momentum_volume", direction="buy",
        entry_price=Decimal("100"), stop_loss=Decimal("95"), take_profit=Decimal("120"), size_quote=Decimal("1000000"),
        exit_client_order_id="exit-abc",
    )

    # قیمت لحظه‌ای (۱۰۵) بین SL و TP است — روش قدیمی این رو باز نگه می‌داشت
    runner._check_exits(track)

    order_executor.client.get_order_status.assert_called_once_with(client_order_id="exit-abc")
    assert "BTCIRT" not in track.open_positions
    closed = storage.get_closed_paper_trades()
    assert len(closed) == 1
    assert "صرافی" in closed[0]["exit_reason"]
    storage.close()


def test_check_exits_labels_exchange_confirmed_stop_loss_correctly(tmp_path):
    candles = build_trend_series()[:66]
    runner, storage, order_executor, track = make_runner(tmp_path, AlwaysApprove(), candles, latest_price="90")
    order_executor.client.get_order_status.return_value = {"order": {"id": 1, "status": "Done"}}

    trade_id = storage.open_paper_trade(
        "BTCIRT", "trend_momentum_volume", "60", "buy", 1_700_000_000, Decimal("100"), Decimal("1000000"), "test",
        stop_loss=Decimal("95"), take_profit=Decimal("120"), exit_client_order_id="exit-abc",
    )
    track.open_positions["BTCIRT"] = OpenPosition(
        trade_id=trade_id, symbol="BTCIRT", strategy_name="trend_momentum_volume", direction="buy",
        entry_price=Decimal("100"), stop_loss=Decimal("95"), take_profit=Decimal("120"), size_quote=Decimal("1000000"),
        exit_client_order_id="exit-abc",
    )

    runner._check_exits(track)

    closed = storage.get_closed_paper_trades()
    assert closed[0]["exit_reason"].startswith("برخورد Stop Loss")
    assert Decimal(closed[0]["exit_price"]) == Decimal("95")
    storage.close()


def test_check_exits_falls_back_to_price_check_when_exchange_query_fails(tmp_path):
    """اگه استعلام وضعیت از صرافی خطا بده، نباید کل چرخه بشکنه — باید به روش
    قیمتی قبلی (که خودش تست‌شده و قابل‌اعتماده) برگرده."""
    candles = build_trend_series()[:66]
    runner, storage, order_executor, track = make_runner(tmp_path, AlwaysApprove(), candles, latest_price="90")
    order_executor.client.get_order_status.side_effect = RuntimeError("network error")

    trade_id = storage.open_paper_trade(
        "BTCIRT", "trend_momentum_volume", "60", "buy", 1_700_000_000, Decimal("100"), Decimal("1000000"), "test",
        stop_loss=Decimal("95"), take_profit=Decimal("120"), exit_client_order_id="exit-abc",
    )
    track.open_positions["BTCIRT"] = OpenPosition(
        trade_id=trade_id, symbol="BTCIRT", strategy_name="trend_momentum_volume", direction="buy",
        entry_price=Decimal("100"), stop_loss=Decimal("95"), take_profit=Decimal("120"), size_quote=Decimal("1000000"),
        exit_client_order_id="exit-abc",
    )

    runner._check_exits(track)

    assert "BTCIRT" not in track.open_positions
    closed = storage.get_closed_paper_trades()
    assert closed[0]["exit_reason"] == "برخورد Stop Loss (OCO)"
    storage.close()


def test_check_exits_keeps_position_when_exchange_reports_still_active(tmp_path):
    candles = build_trend_series()[:66]
    runner, storage, order_executor, track = make_runner(tmp_path, AlwaysApprove(), candles, latest_price="105")
    order_executor.client.get_order_status.return_value = {"order": {"id": 1, "status": "Active"}}

    trade_id = storage.open_paper_trade(
        "BTCIRT", "trend_momentum_volume", "60", "buy", 1_700_000_000, Decimal("100"), Decimal("1000000"), "test",
        stop_loss=Decimal("95"), take_profit=Decimal("120"), exit_client_order_id="exit-abc",
    )
    track.open_positions["BTCIRT"] = OpenPosition(
        trade_id=trade_id, symbol="BTCIRT", strategy_name="trend_momentum_volume", direction="buy",
        entry_price=Decimal("100"), stop_loss=Decimal("95"), take_profit=Decimal("120"), size_quote=Decimal("1000000"),
        exit_client_order_id="exit-abc",
    )

    runner._check_exits(track)

    assert "BTCIRT" in track.open_positions
    storage.close()


def test_open_position_generates_and_persists_exit_client_order_id(tmp_path):
    candles = build_trend_series()[:66]
    runner, storage, order_executor, track = make_runner(tmp_path, AlwaysApprove(), candles)

    runner.run_once()

    position = track.open_positions["BTCIRT"]
    assert position.exit_client_order_id is not None

    open_trades = storage.get_open_paper_trades()
    assert open_trades[0]["exit_client_order_id"] == position.exit_client_order_id

    # همون ID باید به submit_order سفارش OCO پاس داده شده باشه
    oco_calls = [c for c in order_executor.submit_order.call_args_list if c.kwargs.get("client_order_id")]
    assert len(oco_calls) == 1
    assert oco_calls[0].kwargs["client_order_id"] == position.exit_client_order_id
    storage.close()


def test_restore_state_recovers_exit_client_order_id(tmp_path):
    candles = build_trend_series()[:66]
    runner, storage, _, track = make_runner(tmp_path, AlwaysApprove(), candles, latest_price="90")

    storage.open_paper_trade(
        "BTCIRT", "trend_momentum_volume", "60", "buy", 1_700_000_000, Decimal("100"), Decimal("1000000"), "test",
        stop_loss=Decimal("95"), take_profit=Decimal("120"), exit_client_order_id="exit-xyz",
    )

    runner.restore_state()

    assert track.open_positions["BTCIRT"].exit_client_order_id == "exit-xyz"
    storage.close()


def test_submit_order_uses_provided_client_order_id_for_exit_order(tmp_path):
    from unittest.mock import MagicMock

    from nobitex_bot.data.storage import Storage
    from nobitex_bot.execution.order_executor import OrderExecutor

    client = MagicMock()
    client.place_order.return_value = {"status": "ok", "order": {"id": 1}}
    storage = Storage(tmp_path / "t.sqlite")
    executor = OrderExecutor(client=client, storage=storage)

    executor.submit_order("BTCIRT", "sell", "oco", Decimal("1"), Decimal("100"), client_order_id="my-fixed-id")

    _, kwargs = client.place_order.call_args
    assert kwargs["client_order_id"] == "my-fixed-id"
    intent = storage.get_order_intent("my-fixed-id")
    assert intent is not None
    storage.close()


def test_run_once_calls_reference_collector_with_scanned_symbols_and_resolution(tmp_path):
    """فاز A نقشهٔ چندبازاره: هر چرخه باید سعی کنه دادهٔ مرجع رو برای همون
    نمادهایی که اسکن شدن جمع کنه — با رزولوشن خودِ scanner، نه track."""
    candles = build_trend_series()[:66]
    runner, storage, _order_executor, _track = make_runner(tmp_path, AlwaysReject(), candles)
    runner.scanner.resolution = "60"
    reference_collector = MagicMock()
    runner.reference_collector = reference_collector

    runner.run_once()

    reference_collector.collect.assert_called_once_with(["BTCIRT"], resolution="60")
    storage.close()


def test_run_once_survives_reference_collector_failure(tmp_path):
    """یک خطای غیرمنتظره در جمع‌آوری دادهٔ مرجع نباید مانع اجرای عادی
    چرخهٔ اصلی معاملهٔ نوبیتکس بشه."""
    candles = build_trend_series()[:66]
    runner, storage, order_executor, track = make_runner(tmp_path, AlwaysApprove(), candles)
    reference_collector = MagicMock()
    reference_collector.collect.side_effect = RuntimeError("boom")
    runner.reference_collector = reference_collector

    runner.run_once()  # نباید exception بندازه

    assert "BTCIRT" in track.open_positions
    storage.close()


def test_run_once_records_cycle_duration_in_status_snapshot(tmp_path):
    """صفحهٔ «چرخهٔ اخیر» داشبورد بدون این نمی‌تونه بگه آخرین اجرا چقدر طول
    کشیده — تنها راه فهمیدنش سرزدن به لاگ خام GitHub Actions بود."""
    import json

    from nobitex_bot.data.storage import Storage

    settings = make_settings(tmp_path)
    storage = Storage(tmp_path / "test.sqlite")
    candles = build_trend_series()[:66]

    market_data = MagicMock()
    market_data.get_ohlc_history.return_value = candles
    stat = MagicMock()
    stat.latest = Decimal("100.68")
    market_data.get_all_market_stats.return_value = {"BTCIRT": stat}

    scanner = MagicMock()
    scan_result = MagicMock()
    scan_result.symbol = "BTCIRT"
    scan_result.last_price = Decimal("100.68")
    scan_result.signal_direction = "bullish"
    scan_result.signal_strength = 0.8
    scan_result.composite_score = 0.75
    scanner.scan.return_value = [scan_result]

    track = StrategyTrack(strategy=TrendMomentumVolumeStrategy(), resolution="60", capital=Decimal("10000000"))
    status_path = tmp_path / "status.json"

    runner = PaperTradingRunner(
        settings=settings,
        market_data=market_data,
        scanner=scanner,
        tracks=[track],
        order_executor=MagicMock(),
        storage=storage,
        approval_gate=AlwaysReject(),
        status_snapshot_path=status_path,
    )

    runner.run_once()

    data = json.loads(status_path.read_text(encoding="utf-8"))
    assert data["cycle_duration_seconds"] is not None
    assert data["cycle_duration_seconds"] >= 0
    assert data["watchlist"] == [
        {
            "symbol": "BTCIRT",
            "last_price": "100.68",
            "signal_direction": "bullish",
            "signal_strength": 0.8,
            "composite_score": 0.75,
        }
    ]
    storage.close()


def test_try_enter_ignores_still_forming_last_candle(tmp_path):
    """اگه udf/history کندلِ در حال شکل‌گیریِ لحظهٔ درخواست رو هم برگردونه
    (رفتار معمول endpointهای سبک TradingView UDF)، بدون حذفش، جفتِ
    prev/curr که کراس رو چک می‌کنه دقیقاً یک کندل جابه‌جا می‌شه — کراس
    واقعی (که روی کندل ۶۵، آخرین کندل بسته‌شده، رخ داده) دیگه دیده نمی‌شه
    چون prev هم از پس از کراس می‌شه. این دقیقاً همون سناریوییه که باعث شد
    در production واقعی، با وجود ده‌ها سیگنال در replay آفلاین، هیچ سیگنالی
    زنده هیچ‌وقت به معامله تبدیل نشه."""
    import time

    closed_candles = build_trend_series()[:66]  # کراس صعودی دقیقاً روی کندل ۶۵ (آخرین کندل بسته)
    last_close = closed_candles[-1].close
    still_forming = _candle(int(time.time()), float(last_close), float(last_close), float(last_close), float(last_close), 100)
    candles_with_partial = closed_candles + [still_forming]

    runner, storage, _order_executor, track = make_runner(tmp_path, AlwaysApprove(), candles_with_partial)

    runner.run_once()

    assert "BTCIRT" in track.open_positions
    storage.close()


def test_run_once_skips_reference_collection_when_not_configured(tmp_path):
    candles = build_trend_series()[:66]
    runner, storage, _order_executor, _track = make_runner(tmp_path, AlwaysReject(), candles)
    assert runner.reference_collector is None

    runner.run_once()  # نباید هیچ خطایی بده وقتی collector تنظیم نشده

    storage.close()
