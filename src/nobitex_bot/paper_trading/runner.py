"""ارکستراسیون Paper Trading: اسکن -> سیگنال -> مدیریت ریسک -> تاییدیهٔ
انسانی (نیمه‌خودکار) -> ثبت سفارش روی Testnet -> ثبت نتیجه.

⚠️ ایمنی حیاتی: این runner باید **فقط** با ``NOBITEX_ENV=testnet`` اجرا
بشه. ``PaperTradingRunner`` خودش این رو در ``__init__`` چک می‌کنه و اگه
env روی production باشه، بدون هیچ حرکتی خطا می‌ده — چون فاز ۷ (پول واقعی)
هنوز نیازمند تایید صریح کاربره.

هر چرخهٔ ``run_once`` باید periodically (هر چند دقیقه، هم‌سو با کوتاه‌ترین
تایم‌فریم تست‌شده) صدا زده بشه — نه پیوسته در یک حلقهٔ فشرده.

نکتهٔ مهم دربارهٔ ``market_data`` در برابر ``order_executor``: این دو باید
از دو کلاینت *متفاوت* بسازن — ``market_data`` همیشه به بازار واقعی
(endpointهای عمومی، بدون توکن، بدون ریسک) وصل بشه تا سیگنال‌ها و بررسی
SL/TP بر اساس رفتار واقعی بازار باشن، نه دادهٔ Testnet که لزوماً همون
رفتار رو نداره؛ فقط ``order_executor`` باید به Testnet وصل بشه (چون آنجا
واقعاً سفارش ثبت می‌شه). به ``scripts/run_paper_trading.py`` نگاه کن.

## حافظه + تست هم‌زمان چند استراتژی/تایم‌فریم

هر ترکیب (استراتژی، تایم‌فریم) یک ``StrategyTrack`` مستقله — سرمایهٔ
مجازی، مدیریت ریسک، و پوزیشن‌های باز خودش رو جدا نگه می‌داره (دقیقاً مثل
اجرای موازی چند بک‌تست زنده). این‌طوری می‌شه مثلاً ``trend_momentum_volume``
رو هم‌زمان روی ۱۵ دقیقه و ۴ ساعته تست کرد و بعداً از جدول ``paper_trades``
(که resolution هم توش ذخیره می‌شه) مقایسه‌شون کرد — دقیقاً همون «حافظه»
که هدف/نتیجهٔ هر معامله (خورد یا نه) رو نگه می‌داره. اسکن فرصت‌ها روی یک
تایم‌فریم مرجع (resolution خودِ scanner) مشترکه تا API چندبار برای هر
ترکیب صدا زده نشه؛ فقط دادهٔ کندل برای تولید سیگنال با resolution خودِ
هر track جداگانه خونده می‌شه.
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
class StrategyTrack:
    """یک ترکیب مستقل (استراتژی + تایم‌فریم) با سرمایه/ریسک/پوزیشن‌های خودش —
    برای تست هم‌زمان چند استراتژی در چند تایم‌فریم بدون تداخل حساب‌ها."""

    strategy: Strategy
    resolution: str
    capital: Decimal
    risk_manager: RiskManager = field(default_factory=RiskManager)
    open_positions: dict[str, OpenPosition] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.strategy.name}@{self.resolution}"


@dataclass
class PaperTradingRunner:
    settings: Settings
    market_data: MarketDataService
    scanner: MarketScanner
    tracks: list[StrategyTrack]
    order_executor: OrderExecutor
    storage: Storage
    approval_gate: ApprovalGate
    decision_logger: object | None = None  # nobitex_bot.monitoring.decision_log.DecisionLogger
    status_snapshot_path: object | None = None  # pathlib.Path
    risk_config_path: object | None = None  # pathlib.Path — برای بازخوانی زندهٔ تنظیمات از داشبورد

    def __post_init__(self) -> None:
        if self.settings.env != "testnet":
            raise RuntimeError(
                "PaperTradingRunner فقط روی NOBITEX_ENV=testnet مجازه — فاز ۷ (پول واقعی) "
                "هنوز نیاز به تایید صریح کاربر داره و فعال نشده"
            )

    def run_once(self) -> None:
        self._reload_risk_config_if_configured()

        for track in self.tracks:
            self._check_exits(track)

        opportunities = self.scanner.scan()
        for track in self.tracks:
            if len(track.open_positions) >= track.risk_manager.config.max_concurrent_trades:
                logger.info("[%s] تعداد پوزیشن‌های باز به سقف رسیده — اسکن جدید انجام نمی‌شه", track.label)
                continue
            for opportunity in opportunities:
                if opportunity.symbol in track.open_positions:
                    continue
                if self._try_enter(track, opportunity.symbol):
                    if len(track.open_positions) >= track.risk_manager.config.max_concurrent_trades:
                        break

        self._write_status_snapshot_if_configured()

    def _reload_risk_config_if_configured(self) -> None:
        if self.risk_config_path is None:
            return
        from nobitex_bot.risk.config_store import load_risk_config

        new_config = load_risk_config(self.risk_config_path)
        for track in self.tracks:
            track.risk_manager.config = new_config

    def _write_status_snapshot_if_configured(self) -> None:
        if self.status_snapshot_path is None:
            return
        from nobitex_bot.monitoring.status_snapshot import write_status_snapshot

        write_status_snapshot(self.status_snapshot_path, self.tracks)

    def _try_enter(self, track: StrategyTrack, symbol: str) -> bool:
        now = int(time.time())
        span_seconds = 200 * 3600
        candles = self.market_data.get_ohlc_history(symbol, track.resolution, now - span_seconds, now)
        if len(candles) < MIN_CANDLES_FOR_INDICATORS:
            return False
        df = compute_indicators(candles_to_dataframe(candles))

        stats = self.market_data.get_all_market_stats()
        market_price = stats[symbol].latest if symbol in stats and stats[symbol].latest else None
        if market_price is None:
            return False

        signal = track.strategy.generate_entry_signal(df, symbol)
        if signal is None:
            return False

        if self.decision_logger is not None:
            self.decision_logger.log("entry_signal", symbol, track.strategy.name, signal.reason)

        decision = track.risk_manager.evaluate(signal, track.capital, market_price, len(track.open_positions))
        if not decision.approved:
            logger.info("[%s] سیگنال %s رد شد توسط مدیریت ریسک: %s", track.label, symbol, decision.reason)
            if self.decision_logger is not None:
                self.decision_logger.log("risk_rejected", symbol, track.strategy.name, decision.reason)
            return False

        if not self.approval_gate.request_approval(signal, decision.position_size_quote):
            logger.info("[%s] سیگنال %s توسط کاربر رد شد", track.label, symbol)
            if self.decision_logger is not None:
                self.decision_logger.log("approval_rejected", symbol, track.strategy.name, "کاربر تایید نکرد")
            return False

        self._open_position(track, signal, decision.position_size_quote)
        return True

    def _open_position(self, track: StrategyTrack, signal, size_quote: Decimal) -> None:
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
            signal.symbol, track.strategy.name, track.resolution, signal.direction, int(time.time()),
            signal.entry_price_hint, size_quote, signal.reason,
        )
        track.open_positions[signal.symbol] = OpenPosition(
            trade_id=trade_id,
            symbol=signal.symbol,
            strategy_name=track.strategy.name,
            direction=signal.direction,
            entry_price=signal.entry_price_hint,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            size_quote=size_quote,
        )
        logger.info("[%s] پوزیشن جدید باز شد: %s اندازه=%s", track.label, signal.symbol, size_quote)
        if self.decision_logger is not None:
            self.decision_logger.log(
                "position_opened", signal.symbol, track.strategy.name, signal.reason,
                details={"entry_price": str(signal.entry_price_hint), "stop_loss": str(signal.stop_loss), "take_profit": str(signal.take_profit)},
            )

    def _check_exits(self, track: StrategyTrack) -> None:
        stats = self.market_data.get_all_market_stats()
        for symbol, position in list(track.open_positions.items()):
            current_price = stats.get(symbol).latest if symbol in stats else None
            if current_price is None:
                continue

            hit_sl = current_price <= position.stop_loss if position.direction == "buy" else current_price >= position.stop_loss
            hit_tp = current_price >= position.take_profit if position.direction == "buy" else current_price <= position.take_profit

            if not (hit_sl or hit_tp):
                continue

            exit_price = position.stop_loss if hit_sl else position.take_profit
            exit_reason = "برخورد Stop Loss (OCO)" if hit_sl else "برخورد Take Profit (OCO)"
            self._close_position(track, position, exit_price, exit_reason)

    def _close_position(self, track: StrategyTrack, position: OpenPosition, exit_price: Decimal, exit_reason: str) -> None:
        if position.direction == "buy":
            gross_pnl = (exit_price - position.entry_price) / position.entry_price * position.size_quote
        else:
            gross_pnl = (position.entry_price - exit_price) / position.entry_price * position.size_quote

        fee = position.size_quote * Decimal("0.0025") * 2
        net_pnl = gross_pnl - fee

        self.storage.close_paper_trade(position.trade_id, int(time.time()), exit_price, fee, net_pnl, exit_reason)
        track.risk_manager.record_closed_trade(net_pnl)
        track.capital += net_pnl
        del track.open_positions[position.symbol]
        logger.info("[%s] پوزیشن %s بسته شد: %s (pnl=%s)", track.label, position.symbol, exit_reason, net_pnl)
        if self.decision_logger is not None:
            self.decision_logger.log(
                "position_closed", position.symbol, track.strategy.name, exit_reason,
                details={"exit_price": str(exit_price), "pnl": str(net_pnl)},
            )
