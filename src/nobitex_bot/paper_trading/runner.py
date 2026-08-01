"""ارکستراسیون Paper Trading: اسکن -> سیگنال -> مدیریت ریسک -> تاییدیهٔ
انسانی (نیمه‌خودکار) -> ثبت سفارش روی Testnet -> ثبت نتیجه.

⚠️ ایمنی حیاتی: این runner باید **فقط** با ``NOBITEX_ENV=testnet`` اجرا
بشه. ``PaperTradingRunner`` خودش این رو در ``__init__`` چک می‌کنه و اگه
env روی production باشه، بدون هیچ حرکتی خطا می‌ده — چون فاز ۷ (پول واقعی)
هنوز نیازمند تایید صریح کاربره.

هر چرخهٔ ``run_once`` باید periodically (هر چند دقیقه، هم‌سو با تایم‌فریم
انتخابی) صدا زده بشه — نه پیوسته در یک حلقهٔ فشرده، چون هم به rate limit
احترام می‌ذاره هم با تایم‌فریم ≥۵ دقیقهٔ پروژه سازگاره.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal

from nobitex_bot.analysis.indicators import MIN_CANDLES_FOR_INDICATORS, candles_to_dataframe, compute_indicators
from nobitex_bot.analysis.scanner import MarketScanner
from nobitex_bot.config import Settings
from nobitex_bot.data.market_data import MarketDataService
from nobitex_bot.data.storage import Storage
from nobitex_bot.execution.order_executor import OrderExecutor
from nobitex_bot.paper_trading.approval import ApprovalGate
from nobitex_bot.risk.risk_manager import RiskManager
from nobitex_bot.strategies.base import Strategy

logger = logging.getLogger(__name__)


def _opposite(direction: str) -> str:
    return "sell" if direction == "buy" else "buy"


@dataclass
class OpenPosition:
    trade_id: int
    symbol: str
    strategy_name: str
    direction: str
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    size_quote: Decimal
    exit_client_order_id: str | None = None


@dataclass
class PaperTradingRunner:
    settings: Settings
    market_data: MarketDataService
    scanner: MarketScanner
    strategies: list[Strategy]
    risk_manager: RiskManager
    order_executor: OrderExecutor
    storage: Storage
    approval_gate: ApprovalGate
    capital: Decimal
    resolution: str = "60"
    open_positions: dict[str, OpenPosition] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.settings.env != "testnet":
            raise RuntimeError(
                "PaperTradingRunner فقط روی NOBITEX_ENV=testnet مجازه — فاز ۷ (پول واقعی) "
                "هنوز نیاز به تایید صریح کاربر داره و فعال نشده"
            )

    def run_once(self) -> None:
        self._check_exits()

        if len(self.open_positions) >= self.risk_manager.config.max_concurrent_trades:
            logger.info("تعداد پوزیشن‌های باز به سقف رسیده — اسکن فرصت جدید انجام نمی‌شه")
            return

        for opportunity in self.scanner.scan():
            if opportunity.symbol in self.open_positions:
                continue
            if self._try_enter(opportunity.symbol):
                if len(self.open_positions) >= self.risk_manager.config.max_concurrent_trades:
                    break

    def _try_enter(self, symbol: str) -> bool:
        now = int(time.time())
        span_seconds = 200 * 3600  # تقریبی، کافی برای اندیکاتورها؛ scanner از تنظیمات خودش استفاده می‌کنه
        candles = self.market_data.get_ohlc_history(symbol, self.resolution, now - span_seconds, now)
        if len(candles) < MIN_CANDLES_FOR_INDICATORS:
            return False
        df = compute_indicators(candles_to_dataframe(candles))

        stats = self.market_data.get_all_market_stats()
        market_price = stats[symbol].latest if symbol in stats and stats[symbol].latest else None
        if market_price is None:
            return False

        for strategy in self.strategies:
            signal = strategy.generate_entry_signal(df, symbol)
            if signal is None:
                continue

            decision = self.risk_manager.evaluate(signal, self.capital, market_price, len(self.open_positions))
            if not decision.approved:
                logger.info("سیگنال %s/%s رد شد توسط مدیریت ریسک: %s", symbol, strategy.name, decision.reason)
                continue

            if not self.approval_gate.request_approval(signal, decision.position_size_quote):
                logger.info("سیگنال %s/%s توسط کاربر رد شد", symbol, strategy.name)
                continue

            self._open_position(signal, decision.position_size_quote, strategy.name)
            return True

        return False

    def _open_position(self, signal, size_quote: Decimal, strategy_name: str) -> None:
        amount = size_quote / signal.entry_price_hint

        self.order_executor.submit_order(signal.symbol, signal.direction, "limit", amount, signal.entry_price_hint)

        exit_side = _opposite(signal.direction)
        self.order_executor.submit_order(
            signal.symbol,
            exit_side,
            "oco",
            amount,
            signal.take_profit,
            extra_params={"stopPrice": signal.stop_loss},
        )

        trade_id = self.storage.open_paper_trade(
            signal.symbol, strategy_name, signal.direction, int(time.time()), signal.entry_price_hint,
            size_quote, signal.reason,
        )
        self.open_positions[signal.symbol] = OpenPosition(
            trade_id=trade_id,
            symbol=signal.symbol,
            strategy_name=strategy_name,
            direction=signal.direction,
            entry_price=signal.entry_price_hint,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            size_quote=size_quote,
        )
        logger.info("پوزیشن جدید باز شد: %s (%s) اندازه=%s", signal.symbol, strategy_name, size_quote)

    def _check_exits(self) -> None:
        stats = self.market_data.get_all_market_stats()
        for symbol, position in list(self.open_positions.items()):
            current_price = stats.get(symbol).latest if symbol in stats else None
            if current_price is None:
                continue

            hit_sl = current_price <= position.stop_loss if position.direction == "buy" else current_price >= position.stop_loss
            hit_tp = current_price >= position.take_profit if position.direction == "buy" else current_price <= position.take_profit

            if not (hit_sl or hit_tp):
                continue

            exit_price = position.stop_loss if hit_sl else position.take_profit
            exit_reason = "برخورد Stop Loss (OCO)" if hit_sl else "برخورد Take Profit (OCO)"
            self._close_position(position, exit_price, exit_reason)

    def _close_position(self, position: OpenPosition, exit_price: Decimal, exit_reason: str) -> None:
        if position.direction == "buy":
            gross_pnl = (exit_price - position.entry_price) / position.entry_price * position.size_quote
        else:
            gross_pnl = (position.entry_price - exit_price) / position.entry_price * position.size_quote

        fee = position.size_quote * Decimal("0.0025") * 2
        net_pnl = gross_pnl - fee

        self.storage.close_paper_trade(position.trade_id, int(time.time()), exit_price, fee, net_pnl, exit_reason)
        self.risk_manager.record_closed_trade(net_pnl)
        self.capital += net_pnl
        del self.open_positions[position.symbol]
        logger.info("پوزیشن %s بسته شد: %s (pnl=%s)", position.symbol, exit_reason, net_pnl)
