"""فیلترهای نمایشی Jinja برای داشبورد — عدد، تاریخ/زمان، نماد، جهت و رویداد را
برای یک کاربر فارسی‌زبان غیرفنی خوانا می‌کنن. هیچ منطق معاملاتی این‌جا نیست؛
فقط تبدیل مقادیر خام (Decimal-به-صورت-متن، epoch ثانیه) به چیزی قابل‌خوندن.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_IRAN_TZ = timezone(timedelta(hours=3, minutes=30))  # ایران DST نداره (از ۱۴۰۰ به بعد)

_EVENT_LABELS = {
    "entry_signal": ("سیگنال ورود", "info"),
    "risk_rejected": ("رد شد (مدیریت ریسک)", "warning"),
    "approval_rejected": ("رد شد (کاربر تایید نکرد)", "muted"),
    "position_opened": ("پوزیشن باز شد", "success"),
    "position_closed": ("پوزیشن بسته شد", "neutral"),
}

_SYMBOL_SUFFIXES = ("USDT", "IRT")


def to_persian_digits(value: str) -> str:
    return "".join(_PERSIAN_DIGITS[int(ch)] if ch.isdigit() else ch for ch in value)


def _gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy + 1 if gm > 2 else gy
    days = 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 - 80 + gd + g_d_m[gm - 1]
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + (days % 31)
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


def format_datetime(ts: int | str | None) -> str:
    """epoch ثانیه -> تاریخ شمسی + ساعت به‌وقت ایران، با رقم فارسی. مثال: «۱۴۰۴/۰۵/۱۱ - ۱۶:۴۲»"""
    if ts is None or ts == "":
        return "—"
    try:
        dt = datetime.fromtimestamp(int(ts), tz=_IRAN_TZ)
    except (ValueError, OSError, OverflowError):
        return "—"
    jy, jm, jd = _gregorian_to_jalali(dt.year, dt.month, dt.day)
    text = f"{jy:04d}/{jm:02d}/{jd:02d} - {dt.hour:02d}:{dt.minute:02d}"
    return to_persian_digits(text)


def format_duration(seconds: float | int | None) -> str:
    """ثانیهٔ خام -> «X دقیقه Y ثانیه» با رقم فارسی — برای نمایش مدت چرخهٔ اخیر."""
    if seconds is None:
        return "—"
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return "—"
    minutes, secs = divmod(max(total, 0), 60)
    text = f"{minutes} دقیقه {secs} ثانیه" if minutes else f"{secs} ثانیه"
    return to_persian_digits(text)


def format_number(value: str | Decimal | int | None) -> str:
    """رشتهٔ عددی خام -> با جداکنندهٔ هزارگان، برای خوانایی (بدون تغییر مقدار واقعی)."""
    if value is None or value == "":
        return "—"
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    except InvalidOperation:
        return str(value)
    normalized = decimal_value.normalize()
    sign, digits, exponent = normalized.as_tuple()
    if exponent > 0:
        normalized = normalized.quantize(Decimal(1))
    text = format(normalized, ",f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def format_symbol(symbol: str | None) -> str:
    """«BTCIRT» -> «BTC/IRT» برای خوانایی بهتر."""
    if not symbol:
        return "—"
    for suffix in _SYMBOL_SUFFIXES:
        if symbol.endswith(suffix):
            return f"{symbol[: -len(suffix)]}/{suffix}"
    return symbol


def direction_fa(direction: str | None) -> str:
    return {"buy": "خرید", "sell": "فروش"}.get(direction or "", direction or "—")


def direction_class(direction: str | None) -> str:
    return {"buy": "success", "sell": "danger"}.get(direction or "", "muted")


def event_label(event_type: str | None) -> str:
    return _EVENT_LABELS.get(event_type or "", (event_type or "—", "muted"))[0]


def event_class(event_type: str | None) -> str:
    return _EVENT_LABELS.get(event_type or "", (event_type or "", "muted"))[1]


def pnl_class(value: str | Decimal | None) -> str:
    if value is None or value == "":
        return "muted"
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    except InvalidOperation:
        return "muted"
    if decimal_value > 0:
        return "success"
    if decimal_value < 0:
        return "danger"
    return "muted"


def register_filters(app) -> None:
    app.jinja_env.filters["fdatetime"] = format_datetime
    app.jinja_env.filters["fnumber"] = format_number
    app.jinja_env.filters["fduration"] = format_duration
    app.jinja_env.filters["fsymbol"] = format_symbol
    app.jinja_env.filters["direction_fa"] = direction_fa
    app.jinja_env.filters["direction_class"] = direction_class
    app.jinja_env.filters["event_label"] = event_label
    app.jinja_env.filters["event_class"] = event_class
    app.jinja_env.filters["pnl_class"] = pnl_class
