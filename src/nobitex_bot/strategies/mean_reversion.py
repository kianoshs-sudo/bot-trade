"""استراتژی ۲ — Mean Reversion + RSI + Bollinger Bands.

قوانین ورود:
- Long: قیمت به باند پایین بولینگر رسیده/زیرش رفته (`close <= BBL`) و
  RSI زیر ۳۰ (oversold) — فرض بر بازگشت قیمت به میانگین
- Short: قیمت به باند بالا رسیده (`close >= BBU`) و RSI بالای ۷۰ (overbought)

خروج: رسیدن قیمت به باند میانی (BBM) — یعنی هدف بازگشت به میانگین محقق
شده؛ مستقل از SL/TP.

SL بر اساس ATR (فراتر از نوسان معمول بازار) تا اگه بازار در روند قوی
باشه (نه رنج) و بولینگر باند پشت سر هم لمس بشه، ضرر محدود بمونه. TP اولیه
باند میانی — محافظه‌کارانه‌تر از هدف باند مقابل، هم‌سو با سطح ریسک متعادل.
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

    def generate_entry_signal(self, df: pd.DataFrame, symbol: str) -> TradeSignal | None:
        if len(df) < self.min_candles:
            return None

        curr = df.iloc[-1]
        needed = ["close", "RSI_14", "BBL_20_2.0", "BBM_20_2.0", "BBU_20_2.0", "ATRr_14"]
        if curr[needed].isna().any():
            return None

        close = Decimal(str(curr["close"]))
        atr = Decimal(str(curr["ATRr_14"]))
        bbm = Decimal(str(curr["BBM_20_2.0"]))

        if curr["close"] <= curr["BBL_20_2.0"] and curr["RSI_14"] < RSI_OVERSOLD:
            return TradeSignal(
                symbol=symbol,
                direction="buy",
                entry_price_hint=close,
                stop_loss=close - atr * ATR_STOP_MULTIPLIER,
                take_profit=bbm,
                reason=(
                    f"قیمت به باند پایین بولینگر رسید (close={curr['close']:.4g} <= "
                    f"BBL={curr['BBL_20_2.0']:.4g}) و RSI={curr['RSI_14']:.1f} در ناحیهٔ oversold"
                ),
                strategy_name=self.name,
            )

        if curr["close"] >= curr["BBU_20_2.0"] and curr["RSI_14"] > RSI_OVERBOUGHT:
            return TradeSignal(
                symbol=symbol,
                direction="sell",
                entry_price_hint=close,
                stop_loss=close + atr * ATR_STOP_MULTIPLIER,
                take_profit=bbm,
                reason=(
                    f"قیمت به باند بالای بولینگر رسید (close={curr['close']:.4g} >= "
                    f"BBU={curr['BBU_20_2.0']:.4g}) و RSI={curr['RSI_14']:.1f} در ناحیهٔ overbought"
                ),
                strategy_name=self.name,
            )

        return None

    def should_exit(self, df: pd.DataFrame, position_direction: str) -> tuple[bool, str]:
        curr = df.iloc[-1]
        if curr[["close", "BBM_20_2.0"]].isna().any():
            return False, ""

        if position_direction == "buy" and curr["close"] >= curr["BBM_20_2.0"]:
            return True, "قیمت به باند میانی بولینگر (هدف بازگشت به میانگین) رسید"
        if position_direction == "sell" and curr["close"] <= curr["BBM_20_2.0"]:
            return True, "قیمت به باند میانی بولینگر (هدف بازگشت به میانگین) رسید"
        return False, ""
