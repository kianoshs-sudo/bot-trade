"""متن پیام‌های معاملاتی برای بله/تلگرام — جدا از لایهٔ ارسال تا قابل تست باشد.

چرا بازنویسی شد: پیام قبلی (در ``NotifyingAutoApproveGate``) **قبل از** ثبت
سفارش فرستاده می‌شد و می‌گفت «✅ پوزیشن جدید». در دادهٔ زنده، ۶۷ بار این پیام
رفت و **صفر** پوزیشن باز شد — هر ۶۷ سفارش با ``HTTP401: API key is invalid.``
رد شده بود و کاربر هیچ‌وقت مطلع نشد. علاوه بر آن ``جهت: buy`` انگلیسی بود،
عددها خام و بدون جداکننده و بدون واحد ارز (که با اسکن هم‌زمان بازار ریالی و
تتری حتماً لازم است)، و SL/TP بدون درصد هیچ حسی از ریسک نمی‌داد.

جریان جدید دو پیام است با یک **کد پیوند** مشترک که از ``client_order_id``
مشتق می‌شود — پس نتیجه هم به سیگنالش وصل است و هم در جدول ``order_intents``
قابل ردیابی. هر دو پیام خودکفا هستند (نماد و جهت را تکرار می‌کنند) تا روی
موبایل بدون اسکرول به عقب قابل فهم باشند.
"""

from __future__ import annotations

from decimal import Decimal

from nobitex_bot.strategies.base import TradeSignal
from nobitex_bot.utils.fa import (
    direction_fa,
    fa_money,
    fa_percent,
    fa_price,
    pct_change,
    quote_currency_label,
)

REF_LENGTH = 6


def signal_ref(client_order_id: str | None) -> str:
    """کد کوتاه و خوانا برای پیوند دادن سیگنال به نتیجه‌اش."""
    if not client_order_id:
        return "-" * REF_LENGTH
    return client_order_id.replace("-", "")[:REF_LENGTH].upper()


def _amount_at_level(signal: TradeSignal, size_quote: Decimal, level: Decimal) -> Decimal | None:
    """مبلغ سود یا زیان اگر قیمت به این سطح برسد.

    روی ارزش اسمی پوزیشن حساب می‌شود و کارمزد را در نظر نمی‌گیرد — کارمزد
    هنگام بستن معامله در ``_close_position`` اعمال می‌شود.
    """
    if signal.entry_price_hint == 0:
        return None
    distance = abs(signal.entry_price_hint - level) / signal.entry_price_hint
    return size_quote * distance


def format_signal_message(
    signal: TradeSignal, size_quote: Decimal, ref: str, quote_rate: Decimal = Decimal(1)
) -> str:
    """پیام اول: سیگنال پیدا شد و سفارش در حال ارسال است.

    عمداً هیچ ادعای موفقیتی نمی‌کند — نتیجه پیام جداگانه‌ای دارد.
    """
    unit = quote_currency_label(signal.symbol)
    sl_pct = pct_change(signal.entry_price_hint, signal.stop_loss)
    tp_pct = pct_change(signal.entry_price_hint, signal.take_profit)
    size_in_quote = size_quote / quote_rate if quote_rate else size_quote
    risk = _amount_at_level(signal, size_quote, signal.stop_loss)
    reward = _amount_at_level(signal, size_quote, signal.take_profit)
    risk_in_quote = risk / quote_rate if (risk is not None and quote_rate) else None
    reward_in_quote = reward / quote_rate if (reward is not None and quote_rate) else None

    lines = [
        f"🔵 سیگنال ورود · #{ref}",
        "",
        f"نماد        {signal.symbol}",
        f"استراتژی     {signal.strategy_name}",
        f"جهت         {direction_fa(signal.direction)}",
        "",
        f"ورود        {fa_price(signal.entry_price_hint)} {unit}".rstrip(),
        f"حد ضرر      {fa_price(signal.stop_loss)}   ({fa_percent(sl_pct)})",
        f"حد سود      {fa_price(signal.take_profit)}   ({fa_percent(tp_pct)})",
        "",
        f"حجم         {fa_money(size_in_quote, signal.symbol)}",
    ]
    if reward_in_quote is not None:
        lines.append(f"سود        {fa_money(reward_in_quote, signal.symbol)} اگر حد سود بخورد")
    if risk_in_quote is not None:
        lines.append(f"ریسک        {fa_money(risk_in_quote, signal.symbol)} اگر حد ضرر بخورد")
    if reward_in_quote is not None and risk_in_quote:
        # نسبت، نه قیمت: دو رقم اعشار. fa_price دقتش را با بزرگی عدد تنظیم
        # می‌کند که برای قیمت درست است ولی برای یک نسبت ۰.۹۴۸۱ می‌داد.
        ratio = (reward_in_quote / risk_in_quote).quantize(Decimal("0.01"))
        lines.append(f"سود/ریسک    {fa_price(ratio)}")
    lines += ["", f"دلیل: {signal.reason}", "", "⏳ در حال ارسال سفارش به صرافی…"]
    return "\n".join(lines)


def format_order_placed_message(
    signal: TradeSignal, ref: str, size_in_quote: Decimal, exchange_order_id: str | None = None
) -> str:
    """پیام دوم (موفق): صرافی سفارش را پذیرفت. تنها جایی که ✅ مجاز است."""
    lines = [
        f"✅ سفارش ثبت شد · #{ref}",
        f"{signal.symbol} · {direction_fa(signal.direction)} · {fa_money(size_in_quote, signal.symbol)}",
    ]
    if exchange_order_id:
        lines.append(f"شناسهٔ صرافی: {exchange_order_id}")
    return "\n".join(lines)


def format_order_failed_message(signal: TradeSignal, ref: str, reason: str) -> str:
    """پیام دوم (ناموفق): علت را **عیناً** نقل می‌کند.

    خلاصه‌کردن پیام خطا همان کاری بود که ``HTTP401: API key is invalid.`` را
    یک ماه پنهان نگه داشت.
    """
    return "\n".join([
        f"⛔ سفارش ثبت نشد · #{ref}",
        f"{signal.symbol} · {direction_fa(signal.direction)}",
        f"علت: {reason}",
        "پوزیشنی باز نشد.",
    ])
