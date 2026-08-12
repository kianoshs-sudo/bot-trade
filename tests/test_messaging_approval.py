from decimal import Decimal
from unittest.mock import MagicMock

from nobitex_bot.paper_trading.messaging_approval import MessagingApprovalGate, NotifyingAutoApproveGate
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


def test_notifying_auto_approve_returns_true_immediately_without_waiting():
    """برخلاف MessagingApprovalGate، نباید هیچ‌وقت get_updates رو صدا بزنه یا
    منتظر بمونه — چون Paper Trading پول واقعی نیست و نیازی به تاییدیهٔ
    انسانی نداره؛ فقط باید فوری تایید کنه و یه پیام اطلاع‌رسانی بفرسته."""
    notifier = MagicMock()
    gate = NotifyingAutoApproveGate(notifier=notifier)

    result = gate.request_approval(make_signal(), Decimal("1000000"))

    assert result is True
    notifier.send_message.assert_called_once()
    notifier.get_updates.assert_not_called()


def test_notifying_auto_approve_message_mentions_symbol_and_direction():
    notifier = MagicMock()
    gate = NotifyingAutoApproveGate(notifier=notifier)

    gate.request_approval(make_signal(), Decimal("1000000"))

    sent_text = notifier.send_message.call_args[0][0]
    assert "BTCIRT" in sent_text
    assert "buy" in sent_text


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
