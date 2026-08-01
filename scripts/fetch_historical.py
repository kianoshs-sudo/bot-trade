#!/usr/bin/env python3
"""دانلود دادهٔ تاریخی OHLC همهٔ بازارهای فعال نوبیتکس برای بک‌تست.

نمونهٔ استفاده:
    python scripts/fetch_historical.py --resolution 60 --days 365
    python scripts/fetch_historical.py --symbols BTCIRT,ETHUSDT --resolution 240 --days 180
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nobitex_bot.config import get_settings
from nobitex_bot.data.market_data import MarketDataService
from nobitex_bot.data.storage import Storage
from nobitex_bot.exchange.client import NobitexClient
from nobitex_bot.exchange.endpoints import ALLOWED_RESOLUTIONS
from nobitex_bot.utils.logging import setup_logging

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbols", default="all",
        help="لیست نمادها با کاما جدا شده (مثل BTCIRT,ETHUSDT) یا 'all' برای همهٔ بازارهای فعال",
    )
    parser.add_argument(
        "--resolution", default="60", choices=ALLOWED_RESOLUTIONS,
        help="تایم‌فریم کندل (حداقل 5 — اسکالپ ممنوع)",
    )
    parser.add_argument("--days", type=int, default=365, help="تعداد روزهای گذشته برای دانلود")
    parser.add_argument("--sleep", type=float, default=1.0, help="فاصلهٔ زمانی بین درخواست‌ها (ثانیه)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    setup_logging(settings.log_level)

    client = NobitexClient(settings=settings)
    storage = Storage(settings.data_dir / "market_data.sqlite")
    service = MarketDataService(client=client, storage=storage)

    if args.symbols == "all":
        stats = service.get_all_market_stats(use_cache=False)
        symbols = sorted(stats.keys())
        logger.info("تعداد بازارهای فعال شناسایی‌شده: %d", len(symbols))
    else:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

    now_ts = int(time.time())
    from_ts = now_ts - args.days * 24 * 3600

    for i, symbol in enumerate(symbols, start=1):
        logger.info("[%d/%d] دانلود %s (resolution=%s, %d روز)", i, len(symbols), symbol, args.resolution, args.days)
        try:
            candles = service.get_ohlc_history_chunked(
                symbol, args.resolution, from_ts, now_ts, sleep_between_requests=args.sleep
            )
            logger.info("  -> %d کندل ذخیره شد", len(candles))
        except Exception:
            logger.exception("  -> خطا در دانلود %s، ادامه به نماد بعدی", symbol)
        time.sleep(args.sleep)

    storage.close()
    logger.info("دانلود دادهٔ تاریخی تمام شد.")


if __name__ == "__main__":
    main()
