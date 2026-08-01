"""محاسبهٔ اندازهٔ پوزیشن بر اساس درصد مشخصی از سرمایه (نه مقدار ثابت).

فرمول ریسک-محور استاندارد: اندازه‌ای انتخاب می‌شه که اگه SL بخوره، دقیقاً
``risk_pct`` از سرمایهٔ فعلی از دست بره — نه بیشتر، نه کمتر، صرف‌نظر از
این‌که SL چقدر از قیمت ورود فاصله داره (نوسان بالا = پوزیشن کوچیک‌تر،
خودکار). این تابع هم در بک‌تست (فاز ۴) و هم در مدیریت ریسک زنده (همین
فاز) استفاده می‌شه تا منطق بین دو محیط یکسان بمونه.
"""

from __future__ import annotations

from decimal import Decimal


def calculate_position_size(capital: Decimal, risk_pct: Decimal, entry_price: Decimal, stop_loss: Decimal) -> Decimal:
    """ارزش اسمی (notional) پوزیشن به واحد ارز مقصد رو برمی‌گردونه."""
    price_risk = abs(entry_price - stop_loss)
    if price_risk == 0 or capital <= 0:
        return Decimal("0")
    risk_amount = capital * risk_pct
    units = risk_amount / price_risk
    return units * entry_price
