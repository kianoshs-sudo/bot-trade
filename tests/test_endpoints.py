from decimal import Decimal

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


def test_taker_fee_rate_differs_between_rial_and_tether_markets():
    """جدول رسمی کارمزد نوبیتکس (از ``/v2/options`` خودِ صرافی): در پلهٔ پایه
    بازار ریالی ۰.۲۵٪ taker می‌گیره ولی بازار تتری ۰.۱۳٪ — تقریباً نصف.
    کد قبلاً ``0.0025`` رو در دو جا هاردکد کرده بود (با یادداشت «تخمینی،
    verify کن») که برای بازارهای تتری هزینه رو ~۲ برابر بیش‌برآورد می‌کرد —
    مهم شد از وقتی رتبه‌بندی حجم با واحد یکسان، بازارهای تتری رو هم وارد
    اسکن کرد."""
    from nobitex_bot.exchange.endpoints import taker_fee_rate

    assert taker_fee_rate("BTCIRT") == Decimal("0.0025")
    assert taker_fee_rate("BTCUSDT") == Decimal("0.0013")


def test_taker_fee_rate_drops_at_higher_volume_tiers():
    """پله‌ها بر اساس حجم معاملات ۳۰ روزه (به ریال) تعیین می‌شن."""
    from nobitex_bot.exchange.endpoints import taker_fee_rate

    # حجم ۳۰روزه ۵ میلیارد ریال -> پلهٔ سوم
    assert taker_fee_rate("BTCIRT", thirty_day_volume_rls=Decimal("5000000000")) == Decimal("0.0019")
    assert taker_fee_rate("BTCIRT", thirty_day_volume_rls=Decimal("0")) == Decimal("0.0025")
