"""محاسبهٔ متریک‌های مقایسه‌ای بک‌تست: نرخ برد، Max Drawdown، Sharpe Ratio، سود/زیان خالص."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class TradeResult:
    pnl: float  # سود/زیان خالص این معامله (بعد از کسر کارمزد)، به واحد پول


@dataclass(frozen=True)
class BacktestMetrics:
    total_trades: int
    win_rate: float
    net_pnl: float
    net_pnl_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float


def compute_win_rate(trades: list[TradeResult]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.pnl > 0)
    return wins / len(trades)


def compute_max_drawdown_pct(equity_curve: list[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            max_dd = max(max_dd, (peak - value) / peak)
    return max_dd


def compute_sharpe_ratio(equity_curve: list[float], periods_per_year: float) -> float:
    """Sharpe سالانه‌شده بر اساس بازده‌های دوره‌ای equity curve (نرخ بدون ریسک = ۰
    فرض شده — چون در بازار کریپتو معیار استانداری برای نرخ بدون ریسک وجود نداره)."""
    if len(equity_curve) < 3:
        return 0.0
    returns = [
        (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
        for i in range(1, len(equity_curve))
        if equity_curve[i - 1] > 0
    ]
    if len(returns) < 2:
        return 0.0
    std_r = statistics.pstdev(returns)
    if std_r == 0:
        return 0.0
    mean_r = statistics.mean(returns)
    return (mean_r / std_r) * math.sqrt(periods_per_year)


def compute_metrics(
    trades: list[TradeResult],
    equity_curve: list[float],
    initial_capital: float,
    final_capital: float,
    periods_per_year: float,
) -> BacktestMetrics:
    net_pnl = final_capital - initial_capital
    net_pnl_pct = (net_pnl / initial_capital) if initial_capital else 0.0
    return BacktestMetrics(
        total_trades=len(trades),
        win_rate=compute_win_rate(trades),
        net_pnl=net_pnl,
        net_pnl_pct=net_pnl_pct,
        max_drawdown_pct=compute_max_drawdown_pct(equity_curve),
        sharpe_ratio=compute_sharpe_ratio(equity_curve, periods_per_year),
    )
