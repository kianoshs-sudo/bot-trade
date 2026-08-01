#!/usr/bin/env python3
"""اجرای Paper Trading روی Testnet نوبیتکس — بدون پول واقعی.

⚠️ الزامی: NOBITEX_ENV باید در .env روی ``testnet`` باشه و NOBITEX_API_TOKEN
باید توکن Testnet (نه production) باشه. اگه env روی production باشه، این
اسکریپت (از طریق PaperTradingRunner) قبل از هر کاری خطا می‌ده.

می‌شه هم‌زمان چند تایم‌فریم رو برای هر ۳ استراتژی تست کرد (هرکدوم با
سرمایه/ریسک مستقل خودش) تا بعداً از ``paper_trading_report.py`` مقایسه بشن:

    python scripts/run_paper_trading.py --resolutions 15,60,240 --interval-minutes 15 --approval manual
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import replace
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
from nobitex_bot.monitoring.decision_log import DecisionLogger
from nobitex_bot.paper_trading.approval import AutoApproveGate, ManualCLIApprovalGate
from nobitex_bot.paper_trading.runner import PaperTradingRunner, StrategyTrack
from nobitex_bot.risk.config_store import load_risk_config
from nobitex_bot.risk.risk_manager import RiskManager
from nobitex_bot.security.key_storage import SecretStore, WrongMasterPasswordError
from nobitex_bot.strategies.registry import list_strategies, get_strategy
from nobitex_bot.utils.logging import setup_logging

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--resolutions", default="60",
        help="یک یا چند تایم‌فریم با کاما جدا شده (مثل 15,60,240) — هر ترکیب استراتژی×تایم‌فریم یک حساب مجازی مستقل می‌شه",
    )
    parser.add_argument("--scan-resolution", default="60", choices=ALLOWED_RESOLUTIONS, help="تایم‌فریم مرجع برای رتبه‌بندی فرصت‌ها")
    parser.add_argument("--interval-minutes", type=int, default=15, help="فاصلهٔ هر چرخهٔ اسکن+تصمیم")
    parser.add_argument("--initial-capital", type=float, default=10_000_000, help="سرمایهٔ مجازی هر ترکیب استراتژی×تایم‌فریم")
    parser.add_argument(
        "--approval", choices=["manual", "auto"], default="manual",
        help="manual=تایید دستی در ترمینال (پیش‌فرض، تا بله/تلگرام در فاز ۸ وصل بشه)؛ auto فقط برای تست",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    setup_logging(settings.log_level)

    if settings.env != "testnet":
        logger.error("NOBITEX_ENV باید 'testnet' باشه (فعلاً: %s) — این اسکریپت اجرا نمی‌شه", settings.env)
        sys.exit(1)

    resolutions = [r.strip() for r in args.resolutions.split(",") if r.strip()]
    for r in resolutions:
        if r not in ALLOWED_RESOLUTIONS:
            logger.error("تایم‌فریم نامعتبر: %s", r)
            sys.exit(1)

    # توکن API رو یا از .env (NOBITEX_API_TOKEN) یا از فایل رمزنگاری‌شدهٔ داشبورد
    # (secrets.enc، فاز ۸) بخون — دومی نیاز به NOBITEX_MASTER_PASSWORD در env داره
    # چون این اسکریپت (برخلاف داشبورد) رمز رو از session نمی‌گیره.
    if not settings.api_token:
        secrets_path = settings.data_dir / "secrets.enc"
        master_password = os.environ.get("NOBITEX_MASTER_PASSWORD")
        if secrets_path.exists() and master_password:
            try:
                token = SecretStore(secrets_path, master_password).get_secret("nobitex_api_token")
            except WrongMasterPasswordError:
                logger.error("NOBITEX_MASTER_PASSWORD اشتباهه — secrets.enc باز نشد")
                sys.exit(1)
            if token:
                settings = replace(settings, api_token=token)
        if not settings.api_token:
            logger.error(
                "NOBITEX_API_TOKEN تنظیم نشده — یا در .env بذارش، یا از داشبورد "
                "(صفحهٔ تنظیمات) ذخیره کن و NOBITEX_MASTER_PASSWORD رو در .env بده"
            )
            sys.exit(1)

    # دادهٔ بازار (قیمت/کندل/اردربوک) همیشه از بازار واقعی خونده می‌شه — این
    # endpointها عمومی‌ان (بدون توکن) و بدون این کار تصمیم‌گیری بر اساس قیمت‌های
    # Testnet انجام می‌شد که لزوماً رفتار بازار واقعی رو نشون نمی‌ده. فقط ثبت
    # سفارش (جایی که پول واقعی درگیر می‌شه) از Testnet رد می‌شه.
    market_client = NobitexClient(settings=settings, base_url=settings.api_base_url)
    trading_client = NobitexClient(settings=settings)  # طبق NOBITEX_ENV (باید testnet باشه)

    storage = Storage(settings.data_dir / "paper_trading.sqlite")
    market_data = MarketDataService(client=market_client, storage=storage)
    scanner = MarketScanner(market_data=market_data, resolution=args.scan_resolution)
    order_executor = OrderExecutor(client=trading_client, storage=storage)
    approval_gate = ManualCLIApprovalGate() if args.approval == "manual" else AutoApproveGate()

    # اگه از داشبورد (فاز ۸) تنظیمات ریسک ذخیره شده باشه، همون جایگزین پیش‌فرض می‌شه
    initial_risk_config = load_risk_config(settings.data_dir / "risk_config.json")
    tracks = [
        StrategyTrack(
            strategy=get_strategy(strategy_name),
            resolution=resolution,
            capital=Decimal(str(args.initial_capital)),
            risk_manager=RiskManager(initial_risk_config),
        )
        for strategy_name in list_strategies()
        for resolution in resolutions
    ]
    logger.info("تعداد ترکیب استراتژی×تایم‌فریم فعال: %d (%s)", len(tracks), ", ".join(t.label for t in tracks))

    runner = PaperTradingRunner(
        settings=settings,
        market_data=market_data,
        scanner=scanner,
        tracks=tracks,
        order_executor=order_executor,
        storage=storage,
        approval_gate=approval_gate,
        decision_logger=DecisionLogger(settings.data_dir / "decisions.jsonl"),
        status_snapshot_path=settings.data_dir / "status.json",
        risk_config_path=settings.data_dir / "risk_config.json",
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
