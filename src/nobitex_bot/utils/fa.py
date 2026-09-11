"""فارسی‌سازی مقادیر عددی — مشترک بین داشبورد وب و پیام‌های بله/تلگرام.

چرا مشترک: ابزارهای فارسی‌سازی فقط در ``dashboard/formatting.py`` بودن و
**فقط داشبورد** ازشون استفاده می‌کرد. پیام‌های تلگرام مقدار خام ``Decimal``
می‌فرستادن — چیزی مثل ``اندازهٔ پوزیشن: 26045000.000000`` یا
``جهت: buy`` — بدون جداکنندهٔ هزارگان، بدون واحد ارز، و با صفرهای بی‌معنی.
این ماژول در ``utils`` نشسته تا هر دو لایه بتونن واردش کنن، بدون این‌که
لایهٔ اعلان به لایهٔ داشبورد وابسته بشه.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_MINUS = "‑"  # خط تیرهٔ ریاضی (U+2011) — در متن راست‌به‌چپ بهتر از - معمولی می‌نشیند


def fa_digits(text: str) -> str:
    """رقم‌های لاتین را به فارسی تبدیل می‌کند و بقیهٔ کاراکترها را دست نمی‌زند."""
    return "".join(_PERSIAN_DIGITS[int(ch)] if ch.isdigit() else ch for ch in text)


def _to_decimal(value: Decimal | int | float | str | None) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def fa_int(value: Decimal | int | float | str | None) -> str:
    """عدد صحیح با جداکنندهٔ هزارگان و رقم فارسی."""
    decimal_value = _to_decimal(value)
    if decimal_value is None:
        return "—"
    return fa_digits(f"{int(decimal_value):,}")


def fa_price(value: Decimal | int | float | str | None) -> str:
    """قیمت/مقدار، با تعداد رقم اعشارِ **متناسب با بزرگی عدد**.

    قیمت‌های این صرافی ۹ مرتبهٔ بزرگی فاصله دارن (از ~۰.۰۰۰۱ تتر تا
    ~۶ میلیارد ریال). یک تعداد رقم اعشار ثابت یا عددهای بزرگ رو با صفر شلوغ
    می‌کنه یا عددهای کوچیک رو به صفر گرد می‌کنه؛ پس رقم معنادار نگه داشته
    می‌شه و صفرهای انتهایی بی‌معنی حذف می‌شن.
    """
    decimal_value = _to_decimal(value)
    if decimal_value is None:
        return "—"
    absolute = abs(decimal_value)
    if absolute >= 1000:
        places = 0
    elif absolute >= 1:
        places = 2
    elif absolute >= Decimal("0.01"):
        places = 4
    elif absolute > 0:
        # برای عددهای خیلی کوچیک، تا ۴ رقم معنادار بعد از صفرهای پیشرو
        exponent = absolute.adjusted()  # مثلاً ۰.۰۰۰۰۱۲۳۴ -> -5
        places = min(-exponent + 3, 12)
    else:
        places = 0
    quantized = decimal_value.quantize(Decimal(1).scaleb(-places))
    text = f"{quantized:,f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return fa_digits(text)


def fa_percent(value: Decimal | int | float | str | None, places: int = 1) -> str:
    """درصد با علامت صریح — چون «۷.۵٪» بدون علامت معلوم نمی‌کند سود است یا ضرر."""
    decimal_value = _to_decimal(value)
    if decimal_value is None:
        return "—"
    rounded = decimal_value.quantize(Decimal(1).scaleb(-places))
    sign = _MINUS if rounded < 0 else "+"
    return f"{sign}{fa_digits(f'{abs(rounded):,f}'.rstrip('0').rstrip('.') or '0')}٪"


def quote_currency_label(symbol: str | None) -> str:
    """واحد ارز مقصد بازار، به فارسی. بدون این، عدد اندازهٔ پوزیشن بی‌معناست:
    بازار ریالی و تتری هم‌زمان اسکن می‌شن و ۵۰ میلیون ریال با ۵۰ میلیون تتر
    زمین تا آسمون فرق دارن."""
    if not symbol:
        return ""
    upper = symbol.upper().replace("-", "").replace("_", "")
    if upper.endswith("USDT"):
        return "تتر"
    if upper.endswith("IRT"):
        return "ریال"
    return ""


def fa_money(value: Decimal | int | float | str | None, symbol: str | None = None) -> str:
    """مقدار پولی همراه واحد ارز مقصدِ همان بازار."""
    text = fa_price(value)
    label = quote_currency_label(symbol)
    return f"{text} {label}".strip()


def direction_fa(direction: str | None) -> str:
    return {"buy": "خرید", "sell": "فروش"}.get(direction or "", direction or "—")


def direction_arrow(direction: str | None) -> str:
    return {"buy": "🟢 خرید", "sell": "🔴 فروش"}.get(direction or "", direction or "—")


def pct_change(from_price: Decimal, to_price: Decimal) -> Decimal | None:
    """درصد تغییر از یک قیمت به دیگری — برای نشان‌دادن فاصلهٔ SL/TP که بدون آن
    عددهای خام قیمت هیچ حسی از ریسک نمی‌دهند."""
    if from_price == 0:
        return None
    return (to_price - from_price) / from_price * 100
