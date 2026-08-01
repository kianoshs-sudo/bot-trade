#!/usr/bin/env python3
"""اسکن همهٔ بازارهای فعال نوبیتکس و نمایش N فرصت برتر بر اساس امتیاز ترکیبی.

نمونهٔ استفاده:
    python scripts/scan_markets.py --resolution 60 --top 15
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nobitex_bot.analysis.scanner import MarketScanner
from nobitex_bot.config import get_settings
from nobitex_bot.data.market_data import MarketDataService
from nobitex_bot.data.storage import Storage
from nobitex_bot.exchange.client import NobitexClient
from nobitex_bot.exchange.endpoints import ALLOWED_RESOLUTIONS
from nobitex_bot.utils.logging import setup_logging

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolution", default="60", choices=ALLOWED_RESOLUTIONS)
    parser.add_argument("--lookback", type=int, default=200, help="تعداد کندل برای محاسبهٔ اندیکاتورها")
    parser.add_argument("--top", type=int, default=10, help="تعداد فرصت‌های برتر برای نمایش")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    setup_logging(settings.log_level)

    client = NobitexClient(settings=settings)
    storage = Storage(settings.data_dir / "market_data.sqlite")
    service = MarketDataService(client=client, storage=storage)
    scanner = MarketScanner(market_data=service, resolution=args.resolution, lookback_candles=args.lookback)

    results = scanner.scan()
    logger.info("تعداد بازارهای بررسی‌شده: %d", len(results))

    print(f"\n{'نماد':<15}{'قیمت':<15}{'جهت':<10}{'قدرت سیگنال':<14}{'ATR%':<10}{'امتیاز':<10}")
    print("-" * 74)
    for r in results[: args.top]:
        print(
            f"{r.symbol:<15}{str(r.last_price):<15}{r.signal_direction:<10}"
            f"{r.signal_strength:<14.2f}{r.atr_pct * 100:<10.2f}{r.composite_score:<10.3f}"
        )

    storage.close()


if __name__ == "__main__":
    main()
