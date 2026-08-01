"""موتور بک‌تست — اجرای یک استراتژی روی دادهٔ تاریخی یک نماد با شبیه‌سازی
واقع‌گرایانهٔ کارمزد، حداقل ارزش معامله، و سفارش‌های SL/TP نیتیو (OCO).

نکات طراحی مهم (برای جلوگیری از نتایج بیش‌ازحد خوش‌بینانه/غیرواقعی):

- **بدون Look-ahead bias**: سیگنال ورود از رویِ کندل i محاسبه می‌شه، ولی
  اجرا در قیمت *باز شدن* کندل i+1 شبیه‌سازی می‌شه — دقیقاً چیزی که در فاز
  ۰ به‌عنوان بهترین شیوهٔ Jesse شناسایی شد (معماری بدون look-ahead).
- **شبیه‌سازی SL/TP در محدودهٔ high/low هر کندل** — نه فقط قیمت close —
  چون سفارش OCO واقعی هر لحظه در بازار فعاله، نه فقط در بستهٔ کندل.
- اگه SL و TP هر دو در یک کندل لمس بشن، فرض **محافظه‌کارانه** اینه که SL
  زودتر اجرا شده (نه TP) — نتیجهٔ بک‌تست رو بدبینانه‌تر نه خوش‌بینانه‌تر
  می‌کنه.
- **کارمزد و حداقل ارزش معامله (SmallOrder)** در محاسبهٔ سود/زیان و در
  رد کردن سیگنال‌های خیلی کوچیک لحاظ می‌شن.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal

import pandas as pd

from nobitex_bot.analysis.indicators import MIN_CANDLES_FOR_INDICATORS, candles_to_dataframe, compute_indicators
from nobitex_bot.backtest.metrics import BacktestMetrics, TradeResult, compute_metrics
from nobitex_bot.exchange.endpoints import RESOLUTION_SECONDS, min_order_value_for_symbol
from nobitex_bot.exchange.models import Candle
from nobitex_bot.strategies.base import Strategy

logger = logging.getLogger(__name__)

SECONDS_PER_YEAR = 365 * 24 * 3600


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: Decimal = Decimal("10_000_000")  # پیش‌فرض: ۱۰ میلیون ریال
    risk_per_trade_pct: Decimal = Decimal("0.02")  # ۲٪ سرمایه در معرض ریسک هر معامله (سطح متعادل)
    fee_rate: Decimal = Decimal("0.0025")  # ⚠️ تخمینی — نرخ دقیق کارمزد نوبیتکس رو verify کن


@dataclass
class Trade:
    symbol: str
    strategy_name: str
    direction: str
    entry_time: int
    entry_price: Decimal
    exit_time: int
    exit_price: Decimal
    size_quote: Decimal  # ارزش اسمی پوزیشن (notional) به واحد ارز مقصد
    fee_paid: Decimal
    pnl: Decimal
    exit_reason: str
    entry_reason: str


@dataclass
class BacktestResult:
    symbol: str
    strategy_name: str
    trades: list[Trade] = field(default_factory=list)
    metrics: BacktestMetrics | None = None
    final_capital: Decimal = Decimal("0")
    skipped_small_order_signals: int = 0


class BacktestEngine:
    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()

    def run(
        self, symbol: str, resolution: str, candles: list[Candle], strategy: Strategy
    ) -> BacktestResult:
        df = compute_indicators(candles_to_dataframe(candles))
        if len(df) < MIN_CANDLES_FOR_INDICATORS + 2:
            logger.warning("داده ناکافی برای بک‌تست %s/%s", symbol, strategy.name)
            return BacktestResult(symbol=symbol, strategy_name=strategy.name, final_capital=self.config.initial_capital)

        capital = self.config.initial_capital
        min_order_value = Decimal(min_order_value_for_symbol(symbol))

        position: dict | None = None
        trades: list[Trade] = []
        equity_curve: list[float] = []
        skipped_small_order = 0

        last_index = len(df) - 2  # نیاز به i+1 برای اجرا
        for i in range(MIN_CANDLES_FOR_INDICATORS, last_index + 1):
            window = df.iloc[: i + 1]
            next_candle = df.iloc[i + 1]

            if position is not None:
                exit_price, exit_reason = self._check_exit(position, next_candle, window, strategy)
                if exit_price is not None:
                    trade, capital = self._close_position(
                        position, exit_price, exit_reason, next_candle, capital, symbol, strategy.name
                    )
                    trades.append(trade)
                    position = None
            else:
                signal = strategy.generate_entry_signal(window, symbol)
                if signal is not None:
                    size_quote = self._position_size(capital, signal.entry_price_hint, signal.stop_loss)
                    if size_quote < min_order_value:
                        skipped_small_order += 1
                    else:
                        position = {
                            "direction": signal.direction,
                            "entry_price": Decimal(str(next_candle["open"])),
                            "stop_loss": signal.stop_loss,
                            "take_profit": signal.take_profit,
                            "entry_time": int(next_candle["timestamp"]),
                            "entry_reason": signal.reason,
                            "size_quote": size_quote,
                        }

            mark_price = float(next_candle["close"])
            equity_curve.append(float(capital) + self._unrealized_pnl(position, mark_price))

        if position is not None:
            # پوزیشن باز مونده در انتهای بازهٔ بک‌تست — برای گزارش، به قیمت آخرین کندل بسته می‌شه
            last_candle = df.iloc[-1]
            trade, capital = self._close_position(
                position,
                Decimal(str(last_candle["close"])),
                "پایان بازهٔ بک‌تست (پوزیشن باز بسته شد)",
                last_candle,
                capital,
                symbol,
                strategy.name,
            )
            trades.append(trade)

        periods_per_year = SECONDS_PER_YEAR / RESOLUTION_SECONDS[resolution]
        trade_results = [TradeResult(pnl=float(t.pnl)) for t in trades]
        metrics = compute_metrics(
            trade_results, equity_curve, float(self.config.initial_capital), float(capital), periods_per_year
        )

        return BacktestResult(
            symbol=symbol,
            strategy_name=strategy.name,
            trades=trades,
            metrics=metrics,
            final_capital=capital,
            skipped_small_order_signals=skipped_small_order,
        )

    def _position_size(self, capital: Decimal, entry_price: Decimal, stop_loss: Decimal) -> Decimal:
        """اندازهٔ پوزیشن بر اساس درصد ریسک ثابت از سرمایه (نه مقدار ثابت) —
        طبق فاصلهٔ SL از قیمت ورود. این نسخهٔ ساده‌شدهٔ منطق فاز ۵ است؛ فاز ۵
        قیدهای بیشتری (ضرر روزانه، تعداد معاملات هم‌زمان) روش اضافه می‌کنه."""
        price_risk = abs(entry_price - stop_loss)
        if price_risk == 0:
            return Decimal("0")
        risk_amount = capital * self.config.risk_per_trade_pct
        units = risk_amount / price_risk
        return units * entry_price

    def _check_exit(
        self, position: dict, candle: pd.Series, window: pd.DataFrame, strategy: Strategy
    ) -> tuple[Decimal | None, str]:
        low = Decimal(str(candle["low"]))
        high = Decimal(str(candle["high"]))
        stop_loss = position["stop_loss"]
        take_profit = position["take_profit"]

        if position["direction"] == "buy":
            hit_sl = low <= stop_loss
            hit_tp = high >= take_profit
        else:
            hit_sl = high >= stop_loss
            hit_tp = low <= take_profit

        if hit_sl and hit_tp:
            return stop_loss, "SL و TP هر دو در همین کندل لمس شدن — فرض محافظه‌کارانه: SL زودتر اجرا شد"
        if hit_sl:
            return stop_loss, "برخورد Stop Loss (سفارش نیتیو)"
        if hit_tp:
            return take_profit, "برخورد Take Profit (سفارش نیتیو)"

        should_exit, reason = strategy.should_exit(window, position["direction"])
        if should_exit:
            return Decimal(str(candle["open"])), reason

        return None, ""

    def _close_position(
        self,
        position: dict,
        exit_price: Decimal,
        exit_reason: str,
        candle: pd.Series,
        capital: Decimal,
        symbol: str,
        strategy_name: str,
    ) -> tuple[Trade, Decimal]:
        entry_price = position["entry_price"]
        size_quote = position["size_quote"]
        direction = position["direction"]

        if direction == "buy":
            gross_pnl = (exit_price - entry_price) / entry_price * size_quote
        else:
            gross_pnl = (entry_price - exit_price) / entry_price * size_quote

        fee = size_quote * self.config.fee_rate * 2  # کارمزد ورود + خروج
        net_pnl = gross_pnl - fee
        new_capital = capital + net_pnl

        trade = Trade(
            symbol=symbol,
            strategy_name=strategy_name,
            direction=direction,
            entry_time=position["entry_time"],
            entry_price=entry_price,
            exit_time=int(candle["timestamp"]),
            exit_price=exit_price,
            size_quote=size_quote,
            fee_paid=fee,
            pnl=net_pnl,
            exit_reason=exit_reason,
            entry_reason=position["entry_reason"],
        )
        return trade, new_capital

    @staticmethod
    def _unrealized_pnl(position: dict | None, mark_price: float) -> float:
        if position is None:
            return 0.0
        entry_price = float(position["entry_price"])
        size_quote = float(position["size_quote"])
        if position["direction"] == "buy":
            return (mark_price - entry_price) / entry_price * size_quote
        return (entry_price - mark_price) / entry_price * size_quote
