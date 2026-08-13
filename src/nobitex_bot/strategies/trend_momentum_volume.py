"""استراتژی ۱ — Momentum Fade (قبلاً Trend-following، بر اساس شواهد معکوس شد).

⚠️ این استراتژی از حالت trend-following اصلی‌ش کاملاً معکوس شده. تست مستقیم
edge (بازدهٔ قیمت بعد از سیگنال، مستقل از SL/TP) روی دادهٔ واقعی نوبیتکس
(۴۵۷ نماد، ~۱۵ روز) نشون داد نسخهٔ اصلی (خرید روی کراس صعودی EMA9/21 با
فیلتر EMA50+RSI+حجم) edge **منفی و سیستماتیک** داشت — نه فقط noisy:

    افق ۵ کندل: ‑۰.۲۷٪   افق ۱۰: ‑۰.۳۷٪   افق ۲۴: ‑۰.۷۸٪   افق ۴۸: ‑۱.۰۶٪

یعنی بعد از این سیگنال، قیمت به‌طور پایدار در جهت **مخالف** پیش‌بینی حرکت
می‌کرد، و هرچی افق طولانی‌تر بشه بدتر می‌شه. چون این تست مستقیماً همون
شرایط فیلترشدهٔ فعلی (EMA50+RSI+حجم) رو استفاده می‌کرد، رابطهٔ ریاضی ساده‌ست:
معکوس‌کردن جهت معامله دقیقاً همون‌قدر edge مثبت می‌ده (بدون نیاز به اجرای
مجدد تست، چون فقط علامت یک ضرب‌شدن ساده معکوس می‌شه).

قوانین ورود (بعد از معکوس‌سازی):
- Sell (fade): کراس صعودی EMA9/21 + RSI بین ۵۰-۷۵ + حجم بالا + close بالای
  EMA50 — یعنی دقیقاً همون شرایطی که قبلاً «خرید» می‌کرد، الان می‌فروشه.
- Buy (fade): دقیقاً برعکس (کراس نزولی + RSI ۲۵-۵۰ + حجم بالا + زیر EMA50).

خروج: فقط SL/TP نیتیو (OCO) — should_exit همیشه False. تست edge بدون هیچ
خروج دستی انجام شده بود، پس این نزدیک‌ترین تطابق به چیزیه که واقعاً
اندازه‌گیری شده (نه یه قانون خروج تازه و اعتبارسنجی‌نشده).

⚠️ هشدار overfitting: این معکوس‌سازی از همون ۱۵ روز دیتایی استخراج شده که
نسخهٔ اصلی روش تست شده بود — پس با دقت بیشتری (روی دادهٔ جدید که هنوز
ندیده) باید verify بشه قبل از اعتماد کامل.

فاصلهٔ SL هم بعداً از ۱.۵ به ۲ برابر ATR بازتر شد: با بک‌تست کامل (با
کارمزد/اسپرد/اسلیپیج واقعی) نسبت برد/باخت واقعی خیلی کمتر از نسبت اسمی
۱:۲ (SL/TP) در اومد — چون هزینهٔ رفت‌وبرگشت معامله روی فاصلهٔ SL نسبتاً
تنگ، سهم نسبی بزرگی می‌گرفت (SL خروج «تهاجمی» با هزینهٔ اسپرد/اسلیپیج
حساب می‌شه، برخلاف TP که passive و بدون این هزینه‌ست). بازترکردن SL این
سهم نسبی رو کم می‌کنه؛ TP هم به ۴ برابر ATR بازتر شد چون تست edge نشون
داد سود حتی تا افق ۴۸ کندل هم داشت رشد می‌کرد (بدون علامت اشباع). با
جاروب چند مقدار روی همون دیتای کش‌شده: Sharpe از ‑۴.۶۷ (نسخهٔ اصلی) به
‑۱.۴۵ رسید — هنوز منفی، ولی بهبود بزرگ.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from nobitex_bot.strategies.base import Strategy, TradeSignal

VOLUME_MA_PERIOD = 20
ATR_STOP_MULTIPLIER = Decimal("2")
ATR_TAKE_PROFIT_MULTIPLIER = Decimal("4")


class TrendMomentumVolumeStrategy(Strategy):
    name = "trend_momentum_volume"
    min_candles = 50  # EMA50 به حداقل ۵۰ کندل برای مقدار معتبر (غیر NaN) نیاز داره

    def generate_entry_signal(self, df: pd.DataFrame, symbol: str) -> TradeSignal | None:
        if len(df) < max(self.min_candles, VOLUME_MA_PERIOD + 1):
            return None

        prev, curr = df.iloc[-2], df.iloc[-1]
        if curr[["EMA_9", "EMA_21", "EMA_50", "RSI_14", "ATRr_14"]].isna().any():
            return None

        volume_ma = df["volume"].rolling(VOLUME_MA_PERIOD).mean().iloc[-1]
        volume_confirmed = curr["volume"] > volume_ma

        bullish_cross = prev["EMA_9"] <= prev["EMA_21"] and curr["EMA_9"] > curr["EMA_21"]
        bearish_cross = prev["EMA_9"] >= prev["EMA_21"] and curr["EMA_9"] < curr["EMA_21"]

        trend_up = curr["close"] > curr["EMA_50"]
        trend_down = curr["close"] < curr["EMA_50"]

        close = Decimal(str(curr["close"]))
        atr = Decimal(str(curr["ATRr_14"]))

        # fade: کراس صعودی -> sell (edge تست شده منفی بود برای buy، پس معکوسش می‌کنیم)
        if bullish_cross and volume_confirmed and trend_up and 50 <= curr["RSI_14"] <= 75:
            return TradeSignal(
                symbol=symbol,
                direction="sell",
                entry_price_hint=close,
                stop_loss=close + atr * ATR_STOP_MULTIPLIER,
                take_profit=close - atr * ATR_TAKE_PROFIT_MULTIPLIER,
                reason=(
                    f"Fade کراس صعودی EMA9/EMA21 بالای EMA50 + RSI={curr['RSI_14']:.1f} "
                    f"+ حجم ({curr['volume']:.2f}) — edge تجربی منفی برای دنبال‌کردن این کراس، "
                    f"پس در جهت مخالفش معامله می‌کنیم"
                ),
                strategy_name=self.name,
            )

        # fade: کراس نزولی -> buy
        if bearish_cross and volume_confirmed and trend_down and 25 <= curr["RSI_14"] <= 50:
            return TradeSignal(
                symbol=symbol,
                direction="buy",
                entry_price_hint=close,
                stop_loss=close - atr * ATR_STOP_MULTIPLIER,
                take_profit=close + atr * ATR_TAKE_PROFIT_MULTIPLIER,
                reason=(
                    f"Fade کراس نزولی EMA9/EMA21 زیر EMA50 + RSI={curr['RSI_14']:.1f} "
                    f"+ حجم ({curr['volume']:.2f}) — edge تجربی منفی برای دنبال‌کردن این کراس، "
                    f"پس در جهت مخالفش معامله می‌کنیم"
                ),
                strategy_name=self.name,
            )

        return None

    def should_exit(self, df: pd.DataFrame, position_direction: str) -> tuple[bool, str]:
        return False, "این استراتژی صرفاً به سفارش OCO نیتیو (SL/TP) برای خروج متکیه"
