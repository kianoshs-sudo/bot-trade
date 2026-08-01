"""مدیریت ریسک — دروازهٔ اجباری قبل از هر معاملهٔ واقعی (فاز ۷).

طبق سند پروژه: «هیچ معاملهٔ واقعی نباید بدون عبور از چک‌های این فاز انجام
بشه». این ماژول همهٔ قیدها رو در یک نقطهٔ واحد (``RiskManager.evaluate``)
جمع می‌کنه:

1. Position Sizing بر اساس درصد ثابتی از سرمایه (نه مقدار ثابت)
2. محدودیت حداکثر ضرر روزانه — در صورت رسیدن، معامله تا روز بعد متوقف می‌شه
3. محدودیت تعداد معاملات هم‌زمان باز
4. حداقل ارزش معامله (خطای SmallOrder)
5. محدودهٔ قیمت مجاز نسبت به قیمت لحظهٔ بازار (خطای BadPrice)

هر معامله باید SL/TP داشته باشه (بدون استثنا) — این قید در سطح
``TradeSignal`` (فاز ۳) از قبل اجباریه چون فیلدهای stop_loss/take_profit
اختیاری نیستن، پس اینجا دوباره enforce نمی‌شه؛ فقط مقدارشون برای محاسبهٔ
اندازهٔ پوزیشن استفاده می‌شه.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from nobitex_bot.exchange.endpoints import MAX_PRICE_DEVIATION_RATIO, min_order_value_for_symbol
from nobitex_bot.risk.position_sizing import calculate_position_size
from nobitex_bot.strategies.base import TradeSignal


@dataclass(frozen=True)
class RiskConfig:
    risk_per_trade_pct: Decimal = Decimal("0.02")  # ۲٪ سرمایه در معرض ریسک هر معامله — سطح متعادل
    max_daily_loss_pct: Decimal = Decimal("0.05")  # ۵٪ ضرر روزانه -> توقف تا روز بعد
    max_concurrent_trades: int = 3
    max_price_deviation: Decimal = Decimal(str(MAX_PRICE_DEVIATION_RATIO))  # قید BadPrice


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str
    position_size_quote: Decimal | None = None


class RiskManager:
    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config or RiskConfig()
        self._daily_realized_pnl = Decimal("0")
        self._daily_reference_date: date | None = None

    def _reset_daily_if_new_day(self, now: datetime) -> None:
        today = now.date()
        if self._daily_reference_date != today:
            self._daily_reference_date = today
            self._daily_realized_pnl = Decimal("0")

    def record_closed_trade(self, pnl: Decimal, now: datetime | None = None) -> None:
        """باید بعد از بسته‌شدن هر معامله (سود یا زیان) صدا زده بشه تا شمارندهٔ
        ضرر روزانه به‌روز بمونه."""
        now = now or datetime.now(timezone.utc)
        self._reset_daily_if_new_day(now)
        self._daily_realized_pnl += pnl

    def is_daily_loss_limit_hit(self, capital: Decimal, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        self._reset_daily_if_new_day(now)
        if capital <= 0 or self._daily_realized_pnl >= 0:
            return False
        daily_loss_pct = -self._daily_realized_pnl / capital
        return daily_loss_pct >= self.config.max_daily_loss_pct

    def evaluate(
        self,
        signal: TradeSignal,
        capital: Decimal,
        market_price: Decimal,
        open_trades_count: int,
        now: datetime | None = None,
    ) -> RiskDecision:
        """دروازهٔ اصلی — همهٔ قیدهای فاز ۵ رو به ترتیب چک می‌کنه."""
        now = now or datetime.now(timezone.utc)
        self._reset_daily_if_new_day(now)

        if self.is_daily_loss_limit_hit(capital, now):
            return RiskDecision(
                False,
                f"محدودیت حداکثر ضرر روزانه ({self.config.max_daily_loss_pct * 100:.0f}%) فعال شده — "
                "معامله تا شروع روز بعد متوقفه",
            )

        if open_trades_count >= self.config.max_concurrent_trades:
            return RiskDecision(
                False, f"حداکثر تعداد معاملات هم‌زمان ({self.config.max_concurrent_trades}) پر شده"
            )

        if market_price > 0:
            deviation = abs(signal.entry_price_hint - market_price) / market_price
            if deviation > self.config.max_price_deviation:
                return RiskDecision(
                    False,
                    f"قیمت پیشنهادی {deviation * 100:.1f}% با قیمت لحظه‌ای فاصله داره "
                    f"(حداکثر مجاز {self.config.max_price_deviation * 100:.0f}%) — BadPrice",
                )

        position_size = calculate_position_size(
            capital, self.config.risk_per_trade_pct, signal.entry_price_hint, signal.stop_loss
        )
        if position_size <= 0:
            return RiskDecision(False, "فاصلهٔ SL از قیمت ورود صفره — قابل محاسبه نیست")

        min_order_value = Decimal(min_order_value_for_symbol(signal.symbol))
        if position_size < min_order_value:
            return RiskDecision(
                False,
                f"اندازهٔ پوزیشن محاسبه‌شده ({position_size:.0f}) کمتر از حداقل ارزش معامله "
                f"({min_order_value}) است — SmallOrder",
            )

        return RiskDecision(True, "تایید شد", position_size_quote=position_size)
