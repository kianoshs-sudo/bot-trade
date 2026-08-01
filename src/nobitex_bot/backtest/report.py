"""تجمیع نتایج بک‌تست چند نماد/استراتژی و تولید گزارش مقایسه‌ای."""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from nobitex_bot.backtest.engine import BacktestResult


@dataclass(frozen=True)
class AggregatedMetrics:
    strategy_name: str
    symbols_tested: int
    total_trades: int
    avg_win_rate: float
    avg_net_pnl_pct: float
    avg_max_drawdown_pct: float
    avg_sharpe_ratio: float


def aggregate_by_strategy(results: list[BacktestResult]) -> dict[str, AggregatedMetrics]:
    by_strategy: dict[str, list[BacktestResult]] = {}
    for r in results:
        if r.metrics is None:
            continue
        by_strategy.setdefault(r.strategy_name, []).append(r)

    aggregated: dict[str, AggregatedMetrics] = {}
    for name, group in by_strategy.items():
        aggregated[name] = AggregatedMetrics(
            strategy_name=name,
            symbols_tested=len(group),
            total_trades=sum(r.metrics.total_trades for r in group),
            avg_win_rate=statistics.mean(r.metrics.win_rate for r in group),
            avg_net_pnl_pct=statistics.mean(r.metrics.net_pnl_pct for r in group),
            avg_max_drawdown_pct=statistics.mean(r.metrics.max_drawdown_pct for r in group),
            avg_sharpe_ratio=statistics.mean(r.metrics.sharpe_ratio for r in group),
        )
    return aggregated


def pick_best_strategy(aggregated: dict[str, AggregatedMetrics]) -> str | None:
    """رتبه‌بندی بر اساس Sharpe Ratio میانگین (بازده تعدیل‌شده با ریسک) —
    معیار اصلی سند برای انتخاب بهترین استراتژی در سطح ریسک متعادل."""
    if not aggregated:
        return None
    return max(aggregated.values(), key=lambda m: m.avg_sharpe_ratio).strategy_name


def format_comparison_report(results: list[BacktestResult]) -> str:
    aggregated = aggregate_by_strategy(results)
    best = pick_best_strategy(aggregated)

    lines = [
        f"{'استراتژی':<28}{'نماد':<8}{'معاملات':<10}{'Win Rate':<10}{'Net PnL%':<12}{'MaxDD%':<10}{'Sharpe':<8}",
        "-" * 86,
    ]
    for r in results:
        if r.metrics is None:
            continue
        lines.append(
            f"{r.strategy_name:<28}{r.symbol:<8}{r.metrics.total_trades:<10}"
            f"{r.metrics.win_rate * 100:<10.1f}{r.metrics.net_pnl_pct * 100:<12.2f}"
            f"{r.metrics.max_drawdown_pct * 100:<10.1f}{r.metrics.sharpe_ratio:<8.2f}"
        )

    lines.append("\nخلاصهٔ میانگین به‌ازای هر استراتژی (روی همهٔ نمادهای تست‌شده):")
    lines.append(f"{'استراتژی':<28}{'#نماد':<8}{'#معاملات':<10}{'Win Rate':<10}{'Net PnL%':<12}{'MaxDD%':<10}{'Sharpe':<8}")
    for name, m in sorted(aggregated.items(), key=lambda kv: kv[1].avg_sharpe_ratio, reverse=True):
        marker = "  <-- برترین (بر اساس Sharpe)" if name == best else ""
        lines.append(
            f"{name:<28}{m.symbols_tested:<8}{m.total_trades:<10}{m.avg_win_rate * 100:<10.1f}"
            f"{m.avg_net_pnl_pct * 100:<12.2f}{m.avg_max_drawdown_pct * 100:<10.1f}{m.avg_sharpe_ratio:<8.2f}{marker}"
        )

    if best:
        lines.append(f"\nنتیجه: استراتژی «{best}» بالاترین Sharpe Ratio میانگین رو داره.")
    return "\n".join(lines)
