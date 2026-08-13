"""استراتژی ۳ — Breakout + ATR-based sizing.

قوانین ورود:
- Long: قیمت بسته‌شدن بالاتر از سقف کانال ۲۰ کندل اخیر (بدون احتساب کندل
  فعلی) به‌اندازهٔ حداقل ۰.۲۵ ATR (نه فقط لمس مرزی) + حجم حداقل ۱.۵ برابر
  میانگین — یعنی خروج معتبر و قاطع از رنج، نه نویز
- Short: قیمت بسته‌شدن پایین‌تر از کف کانال ۲۰ کندل اخیر با همون شرایط

بافر ۰.۲۵ ATR و آستانهٔ حجم ۱.۵ برابر بعداً اضافه شدن: بک‌تست روی دادهٔ
واقعی نوبیتکس نشون داد ۶۶٪ معاملات این استراتژی با SL بسته می‌شن —
کلاسیک‌ترین مشکل استراتژی‌های breakout: شکست کاذب (قیمت به‌سختی از کانال
رد می‌شه و بلافاصله برمی‌گرده). شرط لمسِ صرفِ مرز کانال + حجم «فقط
بالاتر از میانگین» خیلی ضعیف بود و شکست‌های ضعیف/کاذب رو هم قبول می‌کرد.

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
BREAKOUT_CONFIRM_ATR_MULTIPLIER = Decimal("0.25")  # حداقل فاصلهٔ close از مرز کانال، برای رد شکست‌های مرزی/کاذب
VOLUME_CONFIRM_MULTIPLIER = 1.5  # حجم باید حداقل ۱.۵ برابر میانگین ۲۰ کندل باشه (قبلاً فقط >۱x بود)


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
        volume_confirmed = curr["volume"] > volume_ma * VOLUME_CONFIRM_MULTIPLIER
        breakout_buffer = curr["ATRr_14"] * float(BREAKOUT_CONFIRM_ATR_MULTIPLIER)

        close = Decimal(str(curr["close"]))
        atr = Decimal(str(curr["ATRr_14"]))

        if curr["close"] > channel_high + breakout_buffer and volume_confirmed:
            return TradeSignal(
                symbol=symbol,
                direction="buy",
                entry_price_hint=close,
                stop_loss=close - atr * ATR_STOP_MULTIPLIER,
                take_profit=close + atr * ATR_TAKE_PROFIT_MULTIPLIER,
                reason=(
                    f"شکست قاطع سقف کانال {CHANNEL_PERIOD} کندل (channel_high={channel_high:.4g}، "
                    f"بافر تاییدیه={breakout_buffer:.4g}) با حجم ({curr['volume']:.2f}) "
                    f"≥ {VOLUME_CONFIRM_MULTIPLIER}× میانگین"
                ),
                strategy_name=self.name,
                native_order_hint="oco",
            )

        if curr["close"] < channel_low - breakout_buffer and volume_confirmed:
            return TradeSignal(
                symbol=symbol,
                direction="sell",
                entry_price_hint=close,
                stop_loss=close + atr * ATR_STOP_MULTIPLIER,
                take_profit=close - atr * ATR_TAKE_PROFIT_MULTIPLIER,
                reason=(
                    f"شکست قاطع کف کانال {CHANNEL_PERIOD} کندل (channel_low={channel_low:.4g}، "
                    f"بافر تاییدیه={breakout_buffer:.4g}) با حجم ({curr['volume']:.2f}) "
                    f"≥ {VOLUME_CONFIRM_MULTIPLIER}× میانگین"
                ),
                strategy_name=self.name,
                native_order_hint="oco",
            )

        return None

    def should_exit(self, df: pd.DataFrame, position_direction: str) -> tuple[bool, str]:
        return False, "این استراتژی صرفاً به سفارش OCO نیتیو (SL/TP) برای خروج متکیه"
