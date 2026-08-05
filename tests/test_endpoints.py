import pytest

from nobitex_bot.exchange.endpoints import stats_symbol_to_udf_symbol


@pytest.mark.parametrize(
    "raw_stats_symbol, expected_udf_symbol",
    [
        ("btc-rls", "BTCIRT"),
        ("eth-rls", "ETHIRT"),
        ("celr-usdt", "CELRUSDT"),
        ("arb-usdt", "ARBUSDT"),
        ("1m_btt-rls", "1M_BTTIRT"),
        ("1m_btt-usdt", "1M_BTTUSDT"),
    ],
)
def test_stats_symbol_to_udf_symbol_converts_real_api_formats(raw_stats_symbol, expected_udf_symbol):
    """نمونه‌های واقعی که از پاسخ market/stats روی GitHub Actions مشاهده شد —
    بدون این تبدیل، get_ohlc_history با این نمادهای خام همیشه ۴۰۰ می‌گرفت."""
    assert stats_symbol_to_udf_symbol(raw_stats_symbol) == expected_udf_symbol


def test_stats_symbol_to_udf_symbol_rejects_symbol_without_hyphen():
    with pytest.raises(ValueError):
        stats_symbol_to_udf_symbol("BTCIRT")


def test_stats_symbol_to_udf_symbol_rejects_unknown_quote_currency():
    with pytest.raises(ValueError):
        stats_symbol_to_udf_symbol("btc-eur")
