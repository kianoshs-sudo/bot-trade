"""استراتژی ۳ — Breakout Fade (قبلاً Breakout-following، بر اساس شواهد معکوس شد).

⚠️ این استراتژی از حالت breakout-following اصلی‌ش معکوس شده. تست مستقیم
edge (بازدهٔ قیمت بعد از سیگنال، مستقل از SL/TP) روی دادهٔ واقعی نوبیتکس
(۴۵۷ نماد، ~۱۵ روز)، با همین شرایط فیلترشدهٔ فعلی (بافر ۰.۲۵ ATR + حجم
۱.۵ برابر)، نشون داد نسخهٔ اصلی (خرید روی شکست سقف کانال) edge **منفی و
پایدار** داشت، نه فقط noisy:

    افق ۵ کندل: ‑۰.۴۰٪   افق ۱۰: ‑۰.۴۶٪   افق ۲۴: ‑۰.۶۴٪   افق ۴۸: ‑۰.۵۱٪

یعنی شکست‌های کانال به‌طور سیستماتیک شکست می‌خورن و برمی‌گردن (شکست کاذب
حتی بعد از بافر تاییدیه). چون این تست مستقیماً همین شرایط فعلی رو استفاده
می‌کرد، معکوس‌کردن جهت معامله دقیقاً همون‌قدر edge مثبت می‌ده.

قوانین ورود (بعد از معکوس‌سازی):
- Sell (fade): شکست قاطع سقف کانال ۲۰ کندل (با بافر + حجم قوی) — دقیقاً
  همون شرایطی که قبلاً «خرید» می‌کرد، الان می‌فروشه.
- Buy (fade): دقیقاً برعکس (شکست قاطع کف کانال).

خروج: همچنان فقط SL/TP نیتیو (OCO) — should_exit همیشه False، بدون تغییر
نسبت به قبل (تست edge هم بدون هیچ خروج دستی انجام شده بود).

⚠️ هشدار overfitting: این معکوس‌سازی از همون ۱۵ روز دیتایی استخراج شده که
نسخهٔ اصلی روش تست شده بود — پس با دقت بیشتری (روی دادهٔ جدید که هنوز
ندیده) باید verify بشه قبل از اعتماد کامل.

فاصلهٔ SL هم بعداً از ۲ به ۳ برابر ATR و TP از ۳ به ۴ برابر ATR بازتر شد:
با بک‌تست کامل (با کارمزد/اسپرد/اسلیپیج واقعی)، نسبت برد/باخت واقعی خیلی
کمتر از نسبت اسمی طراحی‌شده در اومد — چون هزینهٔ رفت‌وبرگشت معامله روی
فاصلهٔ SL نسبتاً تنگ سهم نسبی بزرگی می‌گرفت (SL خروج «تهاجمی» با هزینهٔ
اسپرد/اسلیپیج حساب می‌شه، برخلاف TP که passive و بدون این هزینه‌ست). با
جاروب چند مقدار روی همون دیتای کش‌شده: Sharpe از ‑۸.۴۹ (نسخهٔ اصلی) به
‑۱.۹۵ رسید — هنوز منفی، ولی بهبود بزرگ.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from nobitex_bot.strategies.base import Strategy, TradeSignal

CHANNEL_PERIOD = 20
VOLUME_MA_PERIOD = 20
ATR_STOP_MULTIPLIER = Decimal("3")
ATR_TAKE_PROFIT_MULTIPLIER = Decimal("4")
BREAKOUT_CONFIRM_ATR_MULTIPLIER = Decimal("0.25")  # حداقل فاصلهٔ close از مرز کانال، برای رد شکست‌های مرزی/کاذب
VOLUME_CONFIRM_MULTIPLIER = 1.5  # حجم باید حداقل ۱.۵ برابر میانگین ۲۰ کندل باشه


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

        # fade: شکست سقف -> sell (edge تست شده منفی بود برای buy، پس معکوسش می‌کنیم)
        if curr["close"] > channel_high + breakout_buffer and volume_confirmed:
            return TradeSignal(
                symbol=symbol,
                direction="sell",
                entry_price_hint=close,
                stop_loss=close + atr * ATR_STOP_MULTIPLIER,
                take_profit=close - atr * ATR_TAKE_PROFIT_MULTIPLIER,
                reason=(
                    f"Fade شکست قاطع سقف کانال {CHANNEL_PERIOD} کندل (channel_high={channel_high:.4g}، "
                    f"بافر تاییدیه={breakout_buffer:.4g}) با حجم ({curr['volume']:.2f}) "
                    f"≥ {VOLUME_CONFIRM_MULTIPLIER}× میانگین — edge تجربی منفی برای دنبال‌کردن این شکست"
                ),
                strategy_name=self.name,
                native_order_hint="oco",
            )

        # fade: شکست کف -> buy
        if curr["close"] < channel_low - breakout_buffer and volume_confirmed:
            return TradeSignal(
                symbol=symbol,
                direction="buy",
                entry_price_hint=close,
                stop_loss=close - atr * ATR_STOP_MULTIPLIER,
                take_profit=close + atr * ATR_TAKE_PROFIT_MULTIPLIER,
                reason=(
                    f"Fade شکست قاطع کف کانال {CHANNEL_PERIOD} کندل (channel_low={channel_low:.4g}، "
                    f"بافر تاییدیه={breakout_buffer:.4g}) با حجم ({curr['volume']:.2f}) "
                    f"≥ {VOLUME_CONFIRM_MULTIPLIER}× میانگین — edge تجربی منفی برای دنبال‌کردن این شکست"
                ),
                strategy_name=self.name,
                native_order_hint="oco",
            )

        return None

    def should_exit(self, df: pd.DataFrame, position_direction: str) -> tuple[bool, str]:
        return False, "این استراتژی صرفاً به سفارش OCO نیتیو (SL/TP) برای خروج متکیه"
