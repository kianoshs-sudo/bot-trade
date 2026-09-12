"""رابط پایهٔ استراتژی‌های ترکیبی (پلاگین‌مانند — اضافه/کم کردن آسون).

هر استراتژی فقط **سیگنال و سطوح پیشنهادی SL/TP** رو مشخص می‌کنه؛ اندازهٔ
پوزیشن (Position Sizing) و اعمال نهایی قیدهای ریسک (فاز ۵) و ارسال واقعی
سفارش (فاز ۷) مسئولیت لایه‌های بالاترن — این جداسازی دقیقاً همون الگویی
هست که در فاز ۰ از freqtrade گرفته شد (strategy پاک/بدون I/O، جدا از
executor).

طبق سند پروژه، خروج از معامله ترجیحاً با سفارش OCO نیتیو نوبیتکس
(stop_market + limit take-profit در یک سفارش) انجام می‌شه، نه با پایش
دستی قیمت در کد.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

import pandas as pd


@dataclass(frozen=True)
class TradeSignal:
    symbol: str
    direction: str  # "buy" | "sell"
    entry_price_hint: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    reason: str
    strategy_name: str
    native_order_hint: str = "oco"  # پیشنهاد نوع سفارش نیتیو نوبیتکس برای مدیریت خروج

    def __post_init__(self) -> None:
        if self.direction not in ("buy", "sell"):
            raise ValueError("direction باید 'buy' یا 'sell' باشه")


def _coerce_param(name: str, default: object, value: object) -> object:
    """مقدار خوانده‌شده از JSON را به نوع پیش‌فرض برمی‌گرداند. ضریب‌هایی که در
    محاسبهٔ قیمت SL/TP ضرب می‌شوند Decimal می‌مانند تا حساب پولی با float نشود."""
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ValueError(f"پارامتر {name} باید true/false باشد، نه {value!r}")
        return value
    if isinstance(default, Decimal):
        return Decimal(str(value))
    if isinstance(default, int):
        return int(value)
    if isinstance(default, float):
        return float(value)
    return value


class Strategy(ABC):
    """کلاس پایه — هر استراتژی جدید فقط باید این دو متد رو پیاده کنه."""

    name: str
    min_candles: int = 35  # هم‌راستا با MIN_CANDLES_FOR_INDICATORS
    # پارامترهای قابل تنظیم با مقدار پیش‌فرض. پروفایل هر سبد (config/portfolios.json)
    # فقط کلیدهایی را که می‌خواهد عوض می‌کند؛ کلید ناشناخته خطاست تا غلط تایپی
    # بی‌صدا به «پیش‌فرض» تبدیل نشود.
    default_params: dict[str, object] = {}

    def __init__(self, **params: object) -> None:
        unknown = set(params) - set(self.default_params)
        if unknown:
            raise ValueError(
                f"پارامتر ناشناخته برای {self.name}: {sorted(unknown)} — مجاز: {sorted(self.default_params)}"
            )
        self.params = {
            key: _coerce_param(key, default, params[key]) if key in params else default
            for key, default in self.default_params.items()
        }

    @abstractmethod
    def generate_entry_signal(self, df: pd.DataFrame, symbol: str) -> TradeSignal | None:
        """اگه شرایط ورود (طبق قوانین این استراتژی) برقرار باشه، TradeSignal برمی‌گردونه."""

    @abstractmethod
    def should_exit(self, df: pd.DataFrame, position_direction: str) -> tuple[bool, str]:
        """سیگنال خروج دستی (مستقل از SL/TP که سفارش OCO/stop نیتیو مدیریت می‌کنه).

        مثلاً معکوس شدن روند. برمی‌گردونه (آیا باید خارج بشه, دلیل)."""

    def has_enough_data(self, df: pd.DataFrame) -> bool:
        return len(df) >= self.min_candles and not df.iloc[-1].isna().any()
