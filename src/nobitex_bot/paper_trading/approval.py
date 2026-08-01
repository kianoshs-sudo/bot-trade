"""دروازهٔ تاییدیهٔ انسانی — طبق تصمیم گرفته‌شده، حالت پیش‌فرض «نیمه‌خودکار»ه:
سیگنال تاییدشده توسط مدیریت ریسک، قبل از ثبت سفارش واقعی (حتی روی Testnet)،
نیاز به تایید صریح داره.

اتصال بله/تلگرام (با دکمه‌های تایید/رد) در فاز ۸ اضافه می‌شه؛ اینجا فقط
رابط انتزاعی + دو پیاده‌سازی ساده (کاملاً خودکار، و پرسش دستی در ترمینال)
تعریف شده تا Paper Trading بدون نیاز به فاز ۸ هم قابل اجرا باشه.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from nobitex_bot.strategies.base import TradeSignal


class ApprovalGate(ABC):
    @abstractmethod
    def request_approval(self, signal: TradeSignal, position_size_quote: Decimal) -> bool:
        """True یعنی معامله تایید شد و می‌شه سفارش رو ثبت کرد."""


class AutoApproveGate(ApprovalGate):
    """تایید کاملاً خودکار — فقط برای تست داخلی/backtest-like شبیه‌سازی؛
    پیش‌فرض Paper Trading و اجرای واقعی نیست."""

    def request_approval(self, signal: TradeSignal, position_size_quote: Decimal) -> bool:
        return True


class ManualCLIApprovalGate(ApprovalGate):
    """تایید/رد دستی از طریق ترمینال — جایگزین موقت بله/تلگرام تا فاز ۸."""

    def request_approval(self, signal: TradeSignal, position_size_quote: Decimal) -> bool:
        print(f"\n[سیگنال جدید] {signal.symbol} — {signal.direction} ({signal.strategy_name})")
        print(f"دلیل: {signal.reason}")
        print(f"ورود: {signal.entry_price_hint}   SL: {signal.stop_loss}   TP: {signal.take_profit}")
        print(f"اندازهٔ پوزیشن پیشنهادی: {position_size_quote}")
        answer = input("تایید می‌کنید؟ [y/N]: ").strip().lower()
        return answer == "y"
