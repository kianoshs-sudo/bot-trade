"""استراتژی ۲ — Mean Reversion + RSI + Bollinger Bands.

قوانین ورود:
- Long: قیمت به باند پایین بولینگر رسیده/زیرش رفته (`close <= BBL`) و
  RSI زیر ۳۰ (oversold) — فرض بر بازگشت قیمت به میانگین
- Short: قیمت به باند بالا رسیده (`close >= BBU`) و RSI بالای ۷۰ (overbought)

خروج: صرفاً سفارش SL/TP نیتیو (OCO) — دقیقاً مثل breakout_atr، نه پایش
دستی باند میانی. (نسخهٔ قبلی هم‌زمان از TP ثابت روی BBM لحظهٔ ورود *و*
should_exit روی BBM لحظه‌به‌لحظه استفاده می‌کرد؛ چون BBM هر کندل جابه‌جا
می‌شه، این دو معیار به مرور از هم فاصله می‌گرفتن و should_exit عملاً قبل
از رسیدن قیمت به TP واقعی، پوزیشن رو زودهنگام می‌بست — طبق بک‌تست، حتی
معاملات «TP-hit» به‌خاطر همین اثر net negative بودن.)

SL بر اساس ATR (فراتر از نوسان معمول بازار) تا اگه بازار در روند قوی
باشه (نه رنج) و بولینگر باند پشت سر هم لمس بشه، ضرر محدود بمونه. TP روی
باند مقابل (نه میانی) — هدف بازگشت کامل به سمت دیگهٔ رنج، نه فقط میانگین؛
با کارمزد و اسپرد واقعی، فاصلهٔ TP تا BBM برای سودآور بودن معامله لازمه.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from nobitex_bot.strategies.base import Strategy, TradeSignal

ATR_STOP_MULTIPLIER = Decimal("1.5")
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70


class MeanReversionStrategy(Strategy):
    name = "mean_reversion_rsi_bb"
    default_params = {
        "atr_stop": ATR_STOP_MULTIPLIER,
        "rsi_oversold": float(RSI_OVERSOLD),
        "rsi_overbought": float(RSI_OVERBOUGHT),
        # چند درصد مانده به باند هم «رسیدن» حساب شود؛ ۰ یعنی فقط لمس یا عبور از باند
        "band_tolerance_pct": 0.0,
    }

    def generate_entry_signal(self, df: pd.DataFrame, symbol: str) -> TradeSignal | None:
        p = self.params
        if len(df) < self.min_candles:
            return None

        curr = df.iloc[-1]
        needed = ["close", "RSI_14", "BBL_20_2.0", "BBM_20_2.0", "BBU_20_2.0", "ATRr_14"]
        if curr[needed].isna().any():
            return None

        close = Decimal(str(curr["close"]))
        atr = Decimal(str(curr["ATRr_14"]))
        bbl = Decimal(str(curr["BBL_20_2.0"]))
        bbu = Decimal(str(curr["BBU_20_2.0"]))

        if curr["close"] <= curr["BBL_20_2.0"] * (1 + p["band_tolerance_pct"]) and curr["RSI_14"] < p["rsi_oversold"]:
            return TradeSignal(
                symbol=symbol,
                direction="buy",
                entry_price_hint=close,
                stop_loss=close - atr * p["atr_stop"],
                take_profit=bbu,
                reason=(
                    f"قیمت به باند پایین بولینگر رسید (close={curr['close']:.4g} <= "
                    f"BBL={curr['BBL_20_2.0']:.4g}) و RSI={curr['RSI_14']:.1f} در ناحیهٔ oversold"
                ),
                strategy_name=self.name,
            )

        if curr["close"] >= curr["BBU_20_2.0"] * (1 - p["band_tolerance_pct"]) and curr["RSI_14"] > p["rsi_overbought"]:
            return TradeSignal(
                symbol=symbol,
                direction="sell",
                entry_price_hint=close,
                stop_loss=close + atr * p["atr_stop"],
                take_profit=bbl,
                reason=(
                    f"قیمت به باند بالای بولینگر رسید (close={curr['close']:.4g} >= "
                    f"BBU={curr['BBU_20_2.0']:.4g}) و RSI={curr['RSI_14']:.1f} در ناحیهٔ overbought"
                ),
                strategy_name=self.name,
            )

        return None

    def should_exit(self, df: pd.DataFrame, position_direction: str) -> tuple[bool, str]:
        return False, "این استراتژی صرفاً به سفارش OCO نیتیو (SL/TP) برای خروج متکیه"
