from decimal import Decimal
from unittest.mock import MagicMock

from nobitex_bot.monitoring.decision_log import DecisionLogger
from nobitex_bot.monitoring.status_snapshot import read_status_snapshot, write_status_snapshot


def test_decision_logger_writes_and_reads_recent(tmp_path):
    logger = DecisionLogger(tmp_path / "decisions.jsonl")

    logger.log("entry_signal", "BTCIRT", "trend_momentum_volume", "کراس صعودی EMA")
    logger.log("position_closed", "BTCIRT", "trend_momentum_volume", "برخورد TP", details={"pnl": "1000"})

    recent = logger.read_recent(10)

    assert len(recent) == 2
    assert recent[0]["event_type"] == "position_closed"  # جدیدترین اول
    assert recent[0]["details"]["pnl"] == "1000"
    assert recent[1]["event_type"] == "entry_signal"


def test_decision_logger_read_recent_limits_count(tmp_path):
    logger = DecisionLogger(tmp_path / "decisions.jsonl")
    for i in range(5):
        logger.log("entry_signal", f"SYM{i}", "s", "r")

    recent = logger.read_recent(2)

    assert len(recent) == 2
    assert recent[0]["symbol"] == "SYM4"


def test_decision_logger_read_recent_empty_when_no_file(tmp_path):
    logger = DecisionLogger(tmp_path / "does_not_exist.jsonl")
    assert logger.read_recent() == []


def test_write_and_read_status_snapshot(tmp_path):
    track = MagicMock()
    track.label = "trend_momentum_volume@60"
    track.strategy.name = "trend_momentum_volume"
    track.resolution = "60"
    track.capital = Decimal("10000000")
    track.open_positions = {"BTCIRT": object()}
    track.risk_manager.is_daily_loss_limit_hit.return_value = False

    path = tmp_path / "status.json"
    write_status_snapshot(path, [track])

    data = read_status_snapshot(path)
    assert data["tracks"][0]["label"] == "trend_momentum_volume@60"
    assert data["tracks"][0]["capital"] == "10000000"
    assert data["tracks"][0]["open_positions"] == 1
    assert data["tracks"][0]["daily_loss_halted"] is False
    assert data["cycle_duration_seconds"] is None


def test_write_status_snapshot_records_cycle_duration(tmp_path):
    track = MagicMock()
    track.label = "trend_momentum_volume@60"
    track.strategy.name = "trend_momentum_volume"
    track.resolution = "60"
    track.capital = Decimal("10000000")
    track.open_positions = {}
    track.risk_manager.is_daily_loss_limit_hit.return_value = False

    path = tmp_path / "status.json"
    write_status_snapshot(path, [track], cycle_duration_seconds=127.4)

    data = read_status_snapshot(path)
    assert data["cycle_duration_seconds"] == 127.4


def test_read_status_snapshot_returns_none_when_missing(tmp_path):
    assert read_status_snapshot(tmp_path / "missing.json") is None
