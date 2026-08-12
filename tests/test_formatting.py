from nobitex_bot.dashboard.formatting import format_duration


def test_format_duration_shows_minutes_and_seconds():
    assert format_duration(127) == "۲ دقیقه ۷ ثانیه"


def test_format_duration_shows_seconds_only_under_a_minute():
    assert format_duration(45) == "۴۵ ثانیه"


def test_format_duration_handles_none():
    assert format_duration(None) == "—"


def test_format_duration_rounds_fractional_seconds():
    assert format_duration(59.6) == "۱ دقیقه ۰ ثانیه"
