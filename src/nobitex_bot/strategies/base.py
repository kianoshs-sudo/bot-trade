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


class Strategy(ABC):
    """کلاس پایه — هر استراتژی جدید فقط باید این دو متد رو پیاده کنه."""

    name: str
    min_candles: int = 35  # هم‌راستا با MIN_CANDLES_FOR_INDICATORS

    @abstractmethod
    def generate_entry_signal(self, df: pd.DataFrame, symbol: str) -> TradeSignal | None:
        """اگه شرایط ورود (طبق قوانین این استراتژی) برقرار باشه، TradeSignal برمی‌گردونه."""

    @abstractmethod
    def should_exit(self, df: pd.DataFrame, position_direction: str) -> tuple[bool, str]:
        """سیگنال خروج دستی (مستقل از SL/TP که سفارش OCO/stop نیتیو مدیریت می‌کنه).

        مثلاً معکوس شدن روند. برمی‌گردونه (آیا باید خارج بشه, دلیل)."""

    def has_enough_data(self, df: pd.DataFrame) -> bool:
        return len(df) >= self.min_candles and not df.iloc[-1].isna().any()
