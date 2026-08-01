#!/usr/bin/env python3
"""گزارش عملکرد Paper Trading — قابل‌مقایسه با متریک‌های بک‌تست (فاز ۴).

نمونهٔ استفاده:
    python scripts/paper_trading_report.py
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nobitex_bot.backtest.metrics import TradeResult, compute_metrics
from nobitex_bot.config import get_settings
from nobitex_bot.data.storage import Storage


def main() -> None:
    settings = get_settings()
    storage = Storage(settings.data_dir / "paper_trading.sqlite")

    closed = storage.get_closed_paper_trades()
    if not closed:
        print("هنوز هیچ معاملهٔ بسته‌شده‌ای در Paper Trading ثبت نشده.")
        return

    by_track: dict[tuple[str, str], list[dict]] = {}
    for row in closed:
        key = (row["strategy_name"], row.get("resolution", "60"))
        by_track.setdefault(key, []).append(row)

    print(f"{'استراتژی@تایم‌فریم':<32}{'معاملات':<10}{'Win Rate':<10}{'Net PnL':<15}")
    print("-" * 67)
    for (strategy_name, resolution), rows in sorted(by_track.items()):
        pnls = [float(Decimal(r["pnl"])) for r in rows if r["pnl"] is not None]
        equity_curve = []
        running = 0.0
        for p in pnls:
            running += p
            equity_curve.append(running)
        trade_results = [TradeResult(pnl=p) for p in pnls]
        # نکته: equity curve اینجا trade-level (نه candle-level مثل بک‌تست) —
        # Sharpe محاسبه‌شده کاملاً هم‌مقیاس بک‌تست نیست، فقط نرخ برد/PnL/Drawdown
        # قابل‌مقایسهٔ مستقیمن.
        metrics = compute_metrics(trade_results, equity_curve or [0.0], 0.0, sum(pnls), periods_per_year=365)
        label = f"{strategy_name}@{resolution}"
        print(f"{label:<32}{len(rows):<10}{metrics.win_rate * 100:<10.1f}{sum(pnls):<15.0f}")

    storage.close()


if __name__ == "__main__":
    main()
