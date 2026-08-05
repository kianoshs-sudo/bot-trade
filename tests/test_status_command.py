from unittest.mock import MagicMock

from nobitex_bot.monitoring.decision_log import DecisionLogger
from nobitex_bot.monitoring.status_snapshot import write_status_snapshot
from nobitex_bot.paper_trading.status_command import format_status_message, handle_status_command


class FakeTrack:
    def __init__(self, label, strategy_name, resolution, capital, open_positions, halted):
        self.label = label
        self.resolution = resolution
        self.capital = capital
        self.open_positions = {f"SYM{i}": object() for i in range(open_positions)}

        class _Strategy:
            name = strategy_name

        self.strategy = _Strategy()

        class _Risk:
            def is_daily_loss_limit_hit(self, capital):
                return halted

        self.risk_manager = _Risk()


def test_handle_status_command_replies_when_keyword_matched(tmp_path):
    notifier = MagicMock()
    notifier.get_updates.return_value = [
        {"update_id": 5, "message": {"text": "وضعیت"}},
    ]

    status_path = tmp_path / "status.json"
    write_status_snapshot(status_path, [FakeTrack("trend@60", "trend_momentum_volume", "60", 1000, 1, False)])
    decision_logger = DecisionLogger(tmp_path / "decisions.jsonl")
    decision_logger.log("position_opened", "BTCIRT", "trend_momentum_volume", "کراس صعودی EMA")

    replied = handle_status_command(
        notifier=notifier,
        status_path=status_path,
        decision_logger=decision_logger,
        offset_path=tmp_path / "offset.txt",
    )

    assert replied is True
    notifier.send_message.assert_called_once()
    sent_text = notifier.send_message.call_args[0][0]
    assert "trend@60" in sent_text
    assert "BTCIRT" in sent_text


def test_handle_status_command_ignores_unrelated_messages(tmp_path):
    notifier = MagicMock()
    notifier.get_updates.return_value = [
        {"update_id": 1, "message": {"text": "تایید"}},
    ]

    replied = handle_status_command(
        notifier=notifier,
        status_path=tmp_path / "status.json",
        decision_logger=DecisionLogger(tmp_path / "decisions.jsonl"),
        offset_path=tmp_path / "offset.txt",
    )

    assert replied is False
    notifier.send_message.assert_not_called()


def test_handle_status_command_persists_offset_across_calls(tmp_path):
    notifier = MagicMock()
    offset_path = tmp_path / "offset.txt"

    notifier.get_updates.return_value = [{"update_id": 10, "message": {"text": "سلام"}}]
    handle_status_command(
        notifier=notifier, status_path=tmp_path / "status.json",
        decision_logger=DecisionLogger(tmp_path / "decisions.jsonl"), offset_path=offset_path,
    )

    notifier.get_updates.reset_mock()
    notifier.get_updates.return_value = []
    handle_status_command(
        notifier=notifier, status_path=tmp_path / "status.json",
        decision_logger=DecisionLogger(tmp_path / "decisions.jsonl"), offset_path=offset_path,
    )

    notifier.get_updates.assert_called_once_with(offset=11)


def test_handle_status_command_returns_false_when_no_updates(tmp_path):
    notifier = MagicMock()
    notifier.get_updates.return_value = []

    replied = handle_status_command(
        notifier=notifier,
        status_path=tmp_path / "status.json",
        decision_logger=DecisionLogger(tmp_path / "decisions.jsonl"),
        offset_path=tmp_path / "offset.txt",
    )

    assert replied is False


def test_format_status_message_shows_halted_track():
    status = {
        "tracks": [
            {"label": "mean_reversion@60", "capital": "9500000", "open_positions": 0, "daily_loss_halted": True},
        ]
    }
    text = format_status_message(status, [])
    assert "⏸️" in text
    assert "mean_reversion@60" in text


def test_format_status_message_handles_no_snapshot_yet():
    text = format_status_message(None, [])
    assert "هنوز هیچ چرخه‌ای کامل نشده" in text
