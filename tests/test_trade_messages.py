from decimal import Decimal

from nobitex_bot.notifications.messages import (
    format_order_failed_message,
    format_order_placed_message,
    format_signal_message,
    signal_ref,
)
from nobitex_bot.strategies.base import TradeSignal


def make_signal(symbol="ADAUSDT", direction="buy", entry="0.2054", sl="0.19", tp="0.22"):
    return TradeSignal(
        symbol=symbol,
        direction=direction,
        entry_price_hint=Decimal(entry),
        stop_loss=Decimal(sl),
        take_profit=Decimal(tp),
        reason="قیمت به باند پایین بولینگر رسید و RSI=28.2",
        strategy_name="mean_reversion_rsi_bb",
    )


def test_signal_ref_is_short_and_derived_from_the_order_id():
    """نتیجه باید به سیگنالش وصل باشد. کد کوتاه از همان ``client_order_id``
    مشتق می‌شود تا در دیتابیس هم قابل ردیابی باشد."""
    ref = signal_ref("d1a6e55a-d000-4aa1-b2d5-60b7f81f84c1")
    assert ref == "D1A6E5"
    assert signal_ref(None) == "------"


def test_signal_message_shows_direction_in_persian_not_english():
    """پیام قبلی ``جهت: buy`` می‌فرستاد."""
    text = format_signal_message(make_signal(), Decimal("63.21"), "D1A6E5", Decimal("211000"))
    assert "خرید" in text
    assert "buy" not in text


def test_signal_message_labels_the_quote_currency_and_groups_digits():
    """عدد خام بدون واحد بی‌معنی بود — بازار ریالی و تتری هم‌زمان اسکن می‌شوند."""
    usdt = format_signal_message(make_signal(), Decimal("63.21"), "AAAAAA", Decimal("211000"))
    assert "تتر" in usdt
    irt = format_signal_message(
        make_signal(symbol="ADAIRT", entry="485660", sl="450000", tp="520000"),
        Decimal("13337662"), "BBBBBB", Decimal("1"),
    )
    assert "ریال" in irt
    assert "۱۳,۳۳۷,۶۶۲" in irt


def test_signal_message_shows_sl_and_tp_as_percentages():
    """قیمت خام SL/TP هیچ حسی از ریسک نمی‌داد."""
    text = format_signal_message(make_signal(), Decimal("63.21"), "AAAAAA", Decimal("211000"))
    assert "٪" in text
    assert "‑۷.۵٪" in text  # (0.19-0.2054)/0.2054
    assert "+۷.۱٪" in text  # (0.22-0.2054)/0.2054


def test_signal_message_shows_the_profit_amount_if_the_target_hits():
    """ریسک بدون سود نیمی از تصویر است — برای تصمیم‌گیری باید هر دو مبلغ دیده
    شوند، نه فقط درصدها."""
    text = format_signal_message(make_signal(), Decimal("13337662"), "AAAAAA", Decimal("211000"))
    # حجم ۶۳.۲۱ تتر، فاصلهٔ TP = ۷.۱۱٪  ->  سود ≈ ۴.۴۹ تتر
    assert "سود" in text
    assert "۴.۴۹ تتر" in text


def test_signal_message_shows_the_reward_to_risk_ratio():
    """نسبت سود به ریسک عددی است که کیفیت معامله را در یک نگاه می‌گوید."""
    text = format_signal_message(make_signal(), Decimal("13337662"), "AAAAAA", Decimal("211000"))
    assert "سود/ریسک" in text
    assert "۰.۹۵" in text  # ۷.۱۱٪ ÷ ۷.۵٪


def test_signal_message_does_not_claim_a_position_was_opened():
    """پیام قبلی «✅ پوزیشن جدید» را **قبل از** ثبت سفارش می‌فرستاد و ۶۷ بار
    موفقیتی را اعلام کرد که هرگز رخ نداد."""
    text = format_signal_message(make_signal(), Decimal("63.21"), "AAAAAA", Decimal("211000"))
    assert "پوزیشن جدید" not in text
    assert "✅" not in text


def test_result_messages_carry_the_same_ref_as_the_signal():
    placed = format_order_placed_message(make_signal(), "D1A6E5", Decimal("63.21"), "12345")
    failed = format_order_failed_message(make_signal(), "D1A6E5", "HTTP401: API key is invalid.")
    for text in (placed, failed):
        assert "D1A6E5" in text
        assert "ADAUSDT" in text  # خودکفا — بدون اسکرول به پیام قبلی قابل فهم


def test_failed_message_quotes_the_exchange_reason_verbatim():
    """علت دقیق، همان چیزی است که عیب‌یابی به آن نیاز دارد."""
    text = format_order_failed_message(make_signal(), "AAAAAA", "HTTP401: API key is invalid.")
    assert "HTTP401: API key is invalid." in text
    assert "⛔" in text
