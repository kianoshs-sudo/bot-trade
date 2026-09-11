import json

import pytest

from nobitex_bot.monitoring.signal_stats import compute_signal_stats, format_signal_stats


def _write_log(tmp_path, records):
    path = tmp_path / "decisions.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def _rec(event_type, symbol="BTCIRT", strategy="s1", reason="r", ts=1_700_000_000):
    return {"ts": ts, "event_type": event_type, "symbol": symbol, "strategy_name": strategy, "reason": reason, "details": {}}


def test_funnel_counts_every_stage(tmp_path):
    """تنها ابزار آماری پروژه فقط معاملات *بسته‌شده* را گزارش می‌داد، پس با صفر
    معامله همیشه «چیزی ثبت نشده» چاپ می‌کرد — در حالی که هزاران سیگنال ثبت شده
    بود و هیچ‌جا دیده نمی‌شد. قیف کامل باید هر مرحله را بشمارد تا معلوم شود
    سیگنال‌ها کجا از بین می‌روند."""
    path = _write_log(tmp_path, [
        _rec("entry_signal"), _rec("risk_rejected"),
        _rec("entry_signal"), _rec("entry_error"),
        _rec("entry_signal"), _rec("position_opened"), _rec("position_closed"),
    ])

    stats = compute_signal_stats(path)

    assert stats.funnel["entry_signal"] == 3
    assert stats.funnel["risk_rejected"] == 1
    assert stats.funnel["entry_error"] == 1
    assert stats.funnel["position_opened"] == 1
    assert stats.funnel["position_closed"] == 1


def test_groups_rejection_and_error_reasons(tmp_path):
    """دلیل رد شدن و دلیل خطا باید تجمیع شوند — در دادهٔ واقعی ۱۰۰٪ ردها یک
    دلیل داشتند و ۱۰۰٪ خطاها یک علت، که بدون تجمیع دیده نمی‌شد."""
    path = _write_log(tmp_path, [
        _rec("risk_rejected", reason="BadPrice"), _rec("risk_rejected", reason="BadPrice"),
        _rec("entry_error", reason="HTTP401"),
    ])

    stats = compute_signal_stats(path)

    assert stats.rejection_reasons["BadPrice"] == 2
    assert stats.error_reasons["HTTP401"] == 1


def test_per_strategy_breakdown(tmp_path):
    path = _write_log(tmp_path, [
        _rec("entry_signal", strategy="a"), _rec("entry_signal", strategy="a"),
        _rec("entry_signal", strategy="b"),
    ])

    stats = compute_signal_stats(path)

    assert stats.signals_by_strategy == {"a": 2, "b": 1}


def test_report_makes_a_total_failure_impossible_to_miss(tmp_path):
    """با ۶۷ خطا و صفر پوزیشن، گزارش باید صریحاً هشدار بدهد — نمایش قبلی
    «۰ پوزیشن» را مثل حالت عادی نشان می‌داد."""
    path = _write_log(tmp_path, [_rec("entry_signal"), _rec("entry_error", reason="HTTP401")])

    text = format_signal_stats(compute_signal_stats(path))

    assert "HTTP401" in text
    assert "۰" in text  # ارقام فارسی
    assert "هیچ پوزیشنی باز نشده" in text


def test_empty_log_does_not_crash(tmp_path):
    stats = compute_signal_stats(_write_log(tmp_path, []))
    assert stats.funnel["entry_signal"] == 0
    assert "سیگنالی ثبت نشده" in format_signal_stats(stats)
