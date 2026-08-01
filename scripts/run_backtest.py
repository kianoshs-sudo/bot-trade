#!/usr/bin/env python3
"""اجرای بک‌تست هر ۳ استراتژی روی دادهٔ تاریخی ذخیره‌شده (توسط fetch_historical.py)
و تولید گزارش مقایسه‌ای.

نمونهٔ استفاده:
    python scripts/run_backtest.py --symbols BTCIRT,ETHIRT,USDTIRT --resolution 60
"""

from __future__ import annotations

import argparse
import logging
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nobitex_bot.backtest.engine import BacktestConfig, BacktestEngine
from nobitex_bot.backtest.report import format_comparison_report
from nobitex_bot.config import get_settings
from nobitex_bot.data.storage import Storage
from nobitex_bot.exchange.endpoints import ALLOWED_RESOLUTIONS
from nobitex_bot.strategies.registry import list_strategies, get_strategy
from nobitex_bot.utils.logging import setup_logging

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", required=True, help="لیست نمادها با کاما جدا شده")
    parser.add_argument("--resolution", default="60", choices=ALLOWED_RESOLUTIONS)
    parser.add_argument("--initial-capital", type=float, default=10_000_000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    setup_logging(settings.log_level)

    storage = Storage(settings.data_dir / "market_data.sqlite")
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    engine = BacktestEngine(config=BacktestConfig(initial_capital=Decimal(str(args.initial_capital))))

    results = []
    for symbol in symbols:
        candles = storage.get_candles(symbol, args.resolution)
        if not candles:
            logger.warning("داده‌ای برای %s در SQLite نیست — اول fetch_historical.py رو اجرا کن", symbol)
            continue
        for strategy_name in list_strategies():
            strategy = get_strategy(strategy_name)
            result = engine.run(symbol, args.resolution, candles, strategy)
            results.append(result)

    print(format_comparison_report(results))
    storage.close()


if __name__ == "__main__":
    main()
