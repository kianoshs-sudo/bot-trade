"""استراتژی کنترل «هر طور شده» — سمت قیمت نسبت به EMA21.

برای سبدهای «راحت» ساخته شد: کاربر آزمایشی خواست که «هر طوری شده» وارد شود
تا داده و دلیل شکست جمع شود. هر وقت اندیکاتورها معتبر باشند سیگنال می‌دهد:
بالای EMA21 خرید، زیرش فروش.

هیچ edge ادعایی ندارد و به همین دلیل در ``list_strategies`` نیست (بک‌تست و حالت
قدیمی را عوض نمی‌کند). نقشش گروه کنترل است: نشان می‌دهد کارمزد و اسپرد با ورودِ
تقریباً بی‌قید چه می‌کنند. در فهرست منابع سبد باید آخر بیاید، وگرنه نوبت به
استراتژی‌های دیگر نمی‌رسد.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from nobitex_bot.strategies.base import Strategy, TradeSignal


class EMA21SideStrategy(Strategy):
    name = "ema21_side"
    default_params = {
        "atr_stop": Decimal("1.5"),
        "atr_take_profit": Decimal("2"),
    }

    def generate_entry_signal(self, df: pd.DataFrame, symbol: str) -> TradeSignal | None:
        if len(df) < self.min_candles:
            return None

        curr = df.iloc[-1]
        if curr[["close", "EMA_21", "ATRr_14"]].isna().any():
            return None

        close = Decimal(str(curr["close"]))
        atr = Decimal(str(curr["ATRr_14"]))
        if atr <= 0 or curr["close"] == curr["EMA_21"]:
            return None

        p = self.params
        if curr["close"] > curr["EMA_21"]:
            return TradeSignal(
                symbol=symbol,
                direction="buy",
                entry_price_hint=close,
                stop_loss=close - atr * p["atr_stop"],
                take_profit=close + atr * p["atr_take_profit"],
                reason=f"گروه کنترل: close={curr['close']:.4g} بالای EMA21={curr['EMA_21']:.4g} — ورود بی‌قید",
                strategy_name=self.name,
            )

        return TradeSignal(
            symbol=symbol,
            direction="sell",
            entry_price_hint=close,
            stop_loss=close + atr * p["atr_stop"],
            take_profit=close - atr * p["atr_take_profit"],
            reason=f"گروه کنترل: close={curr['close']:.4g} زیر EMA21={curr['EMA_21']:.4g} — ورود بی‌قید",
            strategy_name=self.name,
        )

    def should_exit(self, df: pd.DataFrame, position_direction: str) -> tuple[bool, str]:
        return False, "گروه کنترل فقط با SL/TP خارج می‌شود"
