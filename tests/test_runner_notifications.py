from decimal import Decimal
from unittest.mock import MagicMock

from nobitex_bot.paper_trading.runner import PaperTradingRunner, StrategyTrack
from nobitex_bot.risk.risk_manager import RiskConfig, RiskManager
from nobitex_bot.strategies.trend_momentum_volume import TrendMomentumVolumeStrategy
from tests.test_paper_trading import AlwaysApprove, make_settings
from tests.test_strategies import build_trend_series


class _Notifier:
    name = "fake"

    def __init__(self):
        self.sent = []

    def send_message(self, text):
        self.sent.append(text)
        return True

    def get_updates(self, offset=None):
        return []


def _runner(tmp_path, notifier, order_fails=False):
    from nobitex_bot.data.storage import Storage

    storage = Storage(tmp_path / "n.sqlite")
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
    else:
        order_executor.submit_order.return_value = {"status": "ok", "order": {"id": 7788}}

    track = StrategyTrack(
        strategy=TrendMomentumVolumeStrategy(), resolution="60",
        capital=Decimal("50000000"), risk_manager=RiskManager(RiskConfig()),
    )
    runner = PaperTradingRunner(
        settings=make_settings(tmp_path), market_data=market_data, scanner=scanner,
        tracks=[track], order_executor=order_executor, storage=storage,
        approval_gate=AlwaysApprove(), notifier=notifier,
    )
    return runner, storage, track


def test_success_sends_a_signal_message_then_a_placed_message(tmp_path):
    notifier = _Notifier()
    runner, storage, track = _runner(tmp_path, notifier)

    runner.run_once()

    assert len(notifier.sent) >= 2
    signal_msg, result_msg = notifier.sent[0], notifier.sent[1]
    assert "سیگنال ورود" in signal_msg
    assert "در حال ارسال سفارش" in signal_msg
    assert "سفارش ثبت شد" in result_msg
    storage.close()


def test_failure_sends_an_explicit_failure_message_not_a_success_claim(tmp_path):
    """باگ اصلی: پیام «✅ پوزیشن جدید» قبل از ثبت سفارش می‌رفت، پس ۶۷ سفارش
    شکست‌خورده به‌عنوان موفقیت اعلام شدند."""
    notifier = _Notifier()
    runner, storage, track = _runner(tmp_path, notifier, order_fails=True)

    runner.run_once()

    joined = "\n".join(notifier.sent)
    assert "سفارش ثبت نشد" in joined
    assert "HTTP401: API key is invalid." in joined
    assert "سفارش ثبت شد" not in joined
    assert "BTCIRT" not in track.open_positions
    storage.close()


def test_both_messages_share_one_reference_code(tmp_path):
    """نتیجه باید مشخص کند مال کدام سیگنال بوده."""
    notifier = _Notifier()
    runner, storage, _ = _runner(tmp_path, notifier)

    runner.run_once()

    import re
    refs = [re.search(r"#([A-Z0-9]{6})", m) for m in notifier.sent[:2]]
    assert all(refs), "کد پیوند در هر دو پیام نیست"
    assert refs[0].group(1) == refs[1].group(1)
    storage.close()


def test_no_notifier_configured_does_not_break_the_cycle(tmp_path):
    runner, storage, track = _runner(tmp_path, None)

    runner.run_once()

    assert "BTCIRT" in track.open_positions
    storage.close()
