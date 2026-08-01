#!/usr/bin/env python3
"""اجرای Paper Trading روی Testnet نوبیتکس — بدون پول واقعی.

⚠️ الزامی: NOBITEX_ENV باید در .env روی ``testnet`` باشه و NOBITEX_API_TOKEN
باید توکن Testnet (نه production) باشه. اگه env روی production باشه، این
اسکریپت (از طریق PaperTradingRunner) قبل از هر کاری خطا می‌ده.

نمونهٔ استفاده:
    python scripts/run_paper_trading.py --resolution 60 --interval-minutes 15 --approval manual
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nobitex_bot.analysis.scanner import MarketScanner
from nobitex_bot.config import get_settings
from nobitex_bot.data.market_data import MarketDataService
from nobitex_bot.data.storage import Storage
from nobitex_bot.exchange.client import NobitexClient
from nobitex_bot.exchange.endpoints import ALLOWED_RESOLUTIONS
from nobitex_bot.execution.order_executor import OrderExecutor
from nobitex_bot.paper_trading.approval import AutoApproveGate, ManualCLIApprovalGate
from nobitex_bot.paper_trading.runner import PaperTradingRunner
from nobitex_bot.risk.risk_manager import RiskConfig, RiskManager
from nobitex_bot.strategies.registry import list_strategies, get_strategy
from nobitex_bot.utils.logging import setup_logging

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolution", default="60", choices=ALLOWED_RESOLUTIONS)
    parser.add_argument("--interval-minutes", type=int, default=15, help="فاصلهٔ هر چرخهٔ اسکن+تصمیم")
    parser.add_argument("--initial-capital", type=float, default=10_000_000)
    parser.add_argument(
        "--approval", choices=["manual", "auto"], default="manual",
        help="manual=تایید دستی در ترمینال (پیش‌فرض، تا فاز ۸ که بله/تلگرام اضافه بشه)؛ auto فقط برای تست",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    setup_logging(settings.log_level)

    if settings.env != "testnet":
        logger.error("NOBITEX_ENV باید 'testnet' باشه (فعلاً: %s) — این اسکریپت اجرا نمی‌شه", settings.env)
        sys.exit(1)

    client = NobitexClient(settings=settings)
    storage = Storage(settings.data_dir / "paper_trading.sqlite")
    market_data = MarketDataService(client=client, storage=storage)
    scanner = MarketScanner(market_data=market_data, resolution=args.resolution)
    strategies = [get_strategy(name) for name in list_strategies()]
    risk_manager = RiskManager(RiskConfig())
    order_executor = OrderExecutor(client=client, storage=storage)
    approval_gate = ManualCLIApprovalGate() if args.approval == "manual" else AutoApproveGate()

    runner = PaperTradingRunner(
        settings=settings,
        market_data=market_data,
        scanner=scanner,
        strategies=strategies,
        risk_manager=risk_manager,
        order_executor=order_executor,
        storage=storage,
        approval_gate=approval_gate,
        capital=Decimal(str(args.initial_capital)),
        resolution=args.resolution,
    )

    logger.info("شروع Paper Trading روی Testnet — هر %d دقیقه یک چرخه", args.interval_minutes)
    try:
        while True:
            runner.run_once()
            time.sleep(args.interval_minutes * 60)
    except KeyboardInterrupt:
        logger.info("متوقف شد توسط کاربر (Ctrl+C)")
    finally:
        storage.close()


if __name__ == "__main__":
    main()
