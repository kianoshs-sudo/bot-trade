"""استراتژی ۱ — Trend-following + Momentum + Volume.

قوانین ورود:
- Long: کراس صعودی EMA9 روی EMA21 (شروع روند) + RSI بین ۵۰-۷۵ (مومنتوم
  مثبت ولی هنوز overbought نشده) + حجم بالاتر از میانگین ۲۰ کندل اخیر
  (تاییدیهٔ حجمی حرکت)
- Short: دقیقاً برعکس (کراس نزولی + RSI بین ۲۵-۵۰ + حجم بالا)

خروج: کراس معکوس EMA9/EMA21 (سیگنال پایان روند) — مستقل از SL/TP.

SL/TP بر اساس ATR (نه درصد ثابت) تا با نوسان واقعی هر بازار سازگار باشه؛
نسبت ریسک‌به‌ریوارد ۱:۲ که با سطح ریسک متعادل پروژه هم‌خونی داره.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from nobitex_bot.strategies.base import Strategy, TradeSignal

VOLUME_MA_PERIOD = 20
ATR_STOP_MULTIPLIER = Decimal("1.5")
ATR_TAKE_PROFIT_MULTIPLIER = Decimal("3")


class TrendMomentumVolumeStrategy(Strategy):
    name = "trend_momentum_volume"

    def generate_entry_signal(self, df: pd.DataFrame, symbol: str) -> TradeSignal | None:
        if len(df) < max(self.min_candles, VOLUME_MA_PERIOD + 1):
            return None

        prev, curr = df.iloc[-2], df.iloc[-1]
        if curr[["EMA_9", "EMA_21", "RSI_14", "ATRr_14"]].isna().any():
            return None

        volume_ma = df["volume"].rolling(VOLUME_MA_PERIOD).mean().iloc[-1]
        volume_confirmed = curr["volume"] > volume_ma

        bullish_cross = prev["EMA_9"] <= prev["EMA_21"] and curr["EMA_9"] > curr["EMA_21"]
        bearish_cross = prev["EMA_9"] >= prev["EMA_21"] and curr["EMA_9"] < curr["EMA_21"]

        close = Decimal(str(curr["close"]))
        atr = Decimal(str(curr["ATRr_14"]))

        if bullish_cross and volume_confirmed and 50 <= curr["RSI_14"] <= 75:
            return TradeSignal(
                symbol=symbol,
                direction="buy",
                entry_price_hint=close,
                stop_loss=close - atr * ATR_STOP_MULTIPLIER,
                take_profit=close + atr * ATR_TAKE_PROFIT_MULTIPLIER,
                reason=(
                    f"کراس صعودی EMA9/EMA21 + RSI={curr['RSI_14']:.1f} در محدودهٔ مومنتوم مثبت "
                    f"+ حجم ({curr['volume']:.2f}) بالاتر از میانگین {VOLUME_MA_PERIOD} کندل"
                ),
                strategy_name=self.name,
            )

        if bearish_cross and volume_confirmed and 25 <= curr["RSI_14"] <= 50:
            return TradeSignal(
                symbol=symbol,
                direction="sell",
                entry_price_hint=close,
                stop_loss=close + atr * ATR_STOP_MULTIPLIER,
                take_profit=close - atr * ATR_TAKE_PROFIT_MULTIPLIER,
                reason=(
                    f"کراس نزولی EMA9/EMA21 + RSI={curr['RSI_14']:.1f} در محدودهٔ مومنتوم منفی "
                    f"+ حجم ({curr['volume']:.2f}) بالاتر از میانگین {VOLUME_MA_PERIOD} کندل"
                ),
                strategy_name=self.name,
            )

        return None

    def should_exit(self, df: pd.DataFrame, position_direction: str) -> tuple[bool, str]:
        if len(df) < 2:
            return False, ""
        prev, curr = df.iloc[-2], df.iloc[-1]
        if curr[["EMA_9", "EMA_21"]].isna().any():
            return False, ""

        bullish_cross = prev["EMA_9"] <= prev["EMA_21"] and curr["EMA_9"] > curr["EMA_21"]
        bearish_cross = prev["EMA_9"] >= prev["EMA_21"] and curr["EMA_9"] < curr["EMA_21"]

        if position_direction == "buy" and bearish_cross:
            return True, "معکوس شدن روند: EMA9 زیر EMA21 کراس کرد"
        if position_direction == "sell" and bullish_cross:
            return True, "معکوس شدن روند: EMA9 بالای EMA21 کراس کرد"
        return False, ""
