from decimal import Decimal
from unittest.mock import MagicMock

from nobitex_bot.paper_trading.messaging_approval import MessagingApprovalGate
from nobitex_bot.strategies.base import TradeSignal


def make_signal():
    return TradeSignal(
        symbol="BTCIRT", direction="buy", entry_price_hint=Decimal("100"), stop_loss=Decimal("95"),
        take_profit=Decimal("110"), reason="test", strategy_name="test_strategy",
    )


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_approves_when_user_replies_with_approve_keyword(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr("nobitex_bot.paper_trading.messaging_approval.time.monotonic", clock.monotonic)
    monkeypatch.setattr("nobitex_bot.paper_trading.messaging_approval.time.sleep", clock.sleep)

    notifier = MagicMock()
    notifier.get_updates.return_value = [{"update_id": 1, "message": {"text": "تایید"}}]
    gate = MessagingApprovalGate(notifier=notifier, timeout_seconds=60, poll_interval_seconds=5)

    assert gate.request_approval(make_signal(), Decimal("1000000")) is True
    notifier.send_message.assert_called_once()


def test_rejects_when_user_replies_with_reject_keyword(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr("nobitex_bot.paper_trading.messaging_approval.time.monotonic", clock.monotonic)
    monkeypatch.setattr("nobitex_bot.paper_trading.messaging_approval.time.sleep", clock.sleep)

    notifier = MagicMock()
    notifier.get_updates.return_value = [{"update_id": 1, "message": {"text": "رد"}}]
    gate = MessagingApprovalGate(notifier=notifier, timeout_seconds=60, poll_interval_seconds=5)

    assert gate.request_approval(make_signal(), Decimal("1000000")) is False


def test_rejects_by_default_on_timeout_with_no_reply(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr("nobitex_bot.paper_trading.messaging_approval.time.monotonic", clock.monotonic)
    monkeypatch.setattr("nobitex_bot.paper_trading.messaging_approval.time.sleep", clock.sleep)

    notifier = MagicMock()
    notifier.get_updates.return_value = []
    gate = MessagingApprovalGate(notifier=notifier, timeout_seconds=20, poll_interval_seconds=5)

    assert gate.request_approval(make_signal(), Decimal("1000000")) is False


def test_ignores_irrelevant_messages_then_approves(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr("nobitex_bot.paper_trading.messaging_approval.time.monotonic", clock.monotonic)
    monkeypatch.setattr("nobitex_bot.paper_trading.messaging_approval.time.sleep", clock.sleep)

    notifier = MagicMock()
    notifier.get_updates.side_effect = [
        [{"update_id": 1, "message": {"text": "سلام"}}],
        [{"update_id": 2, "message": {"text": "تایید"}}],
    ]
    gate = MessagingApprovalGate(notifier=notifier, timeout_seconds=60, poll_interval_seconds=5)

    assert gate.request_approval(make_signal(), Decimal("1000000")) is True
