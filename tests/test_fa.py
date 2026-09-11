from decimal import Decimal

from nobitex_bot.utils.fa import (
    direction_fa,
    fa_digits,
    fa_int,
    fa_money,
    fa_percent,
    fa_price,
    quote_currency_label,
)


def test_fa_digits_converts_only_digits():
    assert fa_digits("12.5%") == "۱۲.۵%"


def test_fa_int_groups_thousands():
    assert fa_int(1234567) == "۱,۲۳۴,۵۶۷"


def test_fa_price_keeps_small_prices_readable():
    """قیمت‌ها در این بازارها ۹ مرتبه بزرگی فاصله دارن (از ۰.۰۰۰۱ تتر تا
    ۶ میلیارد ریال). یک تعداد رقم اعشار ثابت یا عدد بزرگ رو با صفرهای بی‌معنی
    شلوغ می‌کنه یا عدد کوچیک رو به صفر گرد می‌کنه."""
    assert fa_price(Decimal("6116096940")) == "۶,۱۱۶,۰۹۶,۹۴۰"
    assert fa_price(Decimal("0.2054")) == "۰.۲۰۵۴"
    assert fa_price(Decimal("0.00001234")) == "۰.۰۰۰۰۱۲۳۴"


def test_fa_price_drops_meaningless_trailing_zeros():
    """اندازهٔ پوزیشن در پیام‌ها به‌صورت ``26045000.000000`` می‌رفت."""
    assert fa_price(Decimal("26045000.000000")) == "۲۶,۰۴۵,۰۰۰"


def test_fa_percent_shows_sign():
    assert fa_percent(Decimal("-7.5")) == "‑۷.۵٪"
    assert fa_percent(Decimal("7.12")) == "+۷.۱٪"


def test_fa_money_labels_the_quote_currency():
    """پیام‌ها عدد خام بدون واحد می‌فرستادن — در حالی که بازار ریالی و تتری
    هم‌زمان اسکن می‌شن و ۵۰ میلیون ریال با ۵۰ میلیون تتر زمین تا آسمون فرقه."""
    assert fa_money(Decimal("123.4"), "BTCUSDT") == "۱۲۳.۴ تتر"
    assert fa_money(Decimal("50000000"), "BTCIRT") == "۵۰,۰۰۰,۰۰۰ ریال"


def test_quote_currency_label():
    assert quote_currency_label("ADAUSDT") == "تتر"
    assert quote_currency_label("ADAIRT") == "ریال"


def test_direction_fa():
    assert direction_fa("buy") == "خرید"
    assert direction_fa("sell") == "فروش"
