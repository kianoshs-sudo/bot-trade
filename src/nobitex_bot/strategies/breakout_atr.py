"""استراتژی ۳ — Breakout + ATR-based sizing.

قوانین ورود:
- Long: قیمت بسته‌شدن بالاتر از سقف کانال ۲۰ کندل اخیر (بدون احتساب کندل
  فعلی) + حجم بالاتر از میانگین — یعنی خروج معتبر از رنج، نه نویز
- Short: قیمت بسته‌شدن پایین‌تر از کف کانال ۲۰ کندل اخیر + حجم بالا

خروج: این استراتژی **کاملاً به سفارش OCO نیتیو نوبیتکس (SL+TP) متکی**
است، نه به پایش دستی — دقیقاً طبق توصیهٔ سند پروژه برای استفاده از
قابلیت‌های خود صرافی به‌جای منطق مشابه در کد. به همین خاطر
``should_exit`` همیشه False برمی‌گردونه؛ خروج واقعی رو سفارش OCO ثبت‌شده
در فاز ۷ مدیریت می‌کنه.

SL/TP بر اساس ATR با نسبت ریسک‌به‌ریوارد ۱:۱.۵ (محافظه‌کارانه‌تر از
استراتژی روند، چون breakoutهای کاذب (false breakout) شایع‌ترن).
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from nobitex_bot.strategies.base import Strategy, TradeSignal

CHANNEL_PERIOD = 20
VOLUME_MA_PERIOD = 20
ATR_STOP_MULTIPLIER = Decimal("2")
ATR_TAKE_PROFIT_MULTIPLIER = Decimal("3")


class BreakoutATRStrategy(Strategy):
    name = "breakout_atr"

    def generate_entry_signal(self, df: pd.DataFrame, symbol: str) -> TradeSignal | None:
        if len(df) < max(self.min_candles, CHANNEL_PERIOD + 1):
            return None

        curr = df.iloc[-1]
        if curr[["close", "volume", "ATRr_14"]].isna().any():
            return None

        # کانال بر اساس N کندل *قبل* از کندل فعلی تا breakout واقعی تشخیص داده بشه
        prior = df.iloc[:-1]
        channel_high = prior["high"].tail(CHANNEL_PERIOD).max()
        channel_low = prior["low"].tail(CHANNEL_PERIOD).min()
        volume_ma = df["volume"].rolling(VOLUME_MA_PERIOD).mean().iloc[-1]
        volume_confirmed = curr["volume"] > volume_ma

        close = Decimal(str(curr["close"]))
        atr = Decimal(str(curr["ATRr_14"]))

        if curr["close"] > channel_high and volume_confirmed:
            return TradeSignal(
                symbol=symbol,
                direction="buy",
                entry_price_hint=close,
                stop_loss=close - atr * ATR_STOP_MULTIPLIER,
                take_profit=close + atr * ATR_TAKE_PROFIT_MULTIPLIER,
                reason=(
                    f"شکست سقف کانال {CHANNEL_PERIOD} کندل (channel_high={channel_high:.4g}) "
                    f"با تاییدیهٔ حجم ({curr['volume']:.2f})"
                ),
                strategy_name=self.name,
                native_order_hint="oco",
            )

        if curr["close"] < channel_low and volume_confirmed:
            return TradeSignal(
                symbol=symbol,
                direction="sell",
                entry_price_hint=close,
                stop_loss=close + atr * ATR_STOP_MULTIPLIER,
                take_profit=close - atr * ATR_TAKE_PROFIT_MULTIPLIER,
                reason=(
                    f"شکست کف کانال {CHANNEL_PERIOD} کندل (channel_low={channel_low:.4g}) "
                    f"با تاییدیهٔ حجم ({curr['volume']:.2f})"
                ),
                strategy_name=self.name,
                native_order_hint="oco",
            )

        return None

    def should_exit(self, df: pd.DataFrame, position_direction: str) -> tuple[bool, str]:
        return False, "این استراتژی صرفاً به سفارش OCO نیتیو (SL/TP) برای خروج متکیه"
