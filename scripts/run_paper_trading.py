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
from nobitex_bot.notifications.bale import BaleNotifier
from nobitex_bot.notifications.composite import CompositeNotifier
from nobitex_bot.notifications.telegram import TelegramNotifier
from nobitex_bot.paper_trading.approval import AutoApproveGate, ManualCLIApprovalGate
from nobitex_bot.paper_trading.messaging_approval import MessagingApprovalGate
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
        "--approval", choices=["manual", "auto", "messaging"], default="manual",
        help="manual=تایید دستی در ترمینال؛ messaging=بله/تلگرام؛ auto فقط برای تست",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="فقط یک چرخه اجرا کن و خارج شو (برای GitHub Actions یا هر cron دیگه) — بدون این فلگ، حلقهٔ بی‌نهایت با --interval-minutes اجرا می‌شه",
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

    secrets_path = settings.data_dir / "secrets.enc"
    master_password = os.environ.get("NOBITEX_MASTER_PASSWORD")

    def _get_secret(name: str, env_var: str) -> str | None:
        """اول env var مستقیم (مثلاً GitHub Secret) رو چک می‌کنه، بعد فایل
        رمزنگاری‌شدهٔ داشبورد رو (اگه NOBITEX_MASTER_PASSWORD تنظیم شده باشه)."""
        value = os.environ.get(env_var)
        if value:
            return value
        if secrets_path.exists() and master_password:
            try:
                return SecretStore(secrets_path, master_password).get_secret(name)
            except WrongMasterPasswordError:
                logger.error("NOBITEX_MASTER_PASSWORD اشتباهه — secrets.enc باز نشد")
                sys.exit(1)
        return None

    # احراز هویت: یا کلید API جدید (NOBITEX_API_KEY/NOBITEX_API_SECRET — Ed25519،
    # اولویت با این‌هاست) یا توکن قدیمی (NOBITEX_API_TOKEN). هرکدوم از .env/GitHub
    # Secret یا فایل رمزنگاری‌شدهٔ داشبورد (فاز ۸) قابل تامینه.
    if not (settings.api_key and settings.api_secret):
        api_key = _get_secret("nobitex_api_key", "NOBITEX_API_KEY")
        api_secret = _get_secret("nobitex_api_secret", "NOBITEX_API_SECRET")
        if api_key and api_secret:
            settings = replace(settings, api_key=api_key, api_secret=api_secret)

    if not (settings.api_key and settings.api_secret) and not settings.api_token:
        token = _get_secret("nobitex_api_token", "NOBITEX_API_TOKEN")
        if token:
            settings = replace(settings, api_token=token)
        if not settings.api_token:
            logger.error(
                "هیچ‌کدوم از NOBITEX_API_KEY+NOBITEX_API_SECRET یا NOBITEX_API_TOKEN تنظیم نشده — "
                "یا در .env/GitHub Secret بذارشون، یا از داشبورد (صفحهٔ تنظیمات) ذخیره کن و "
                "NOBITEX_MASTER_PASSWORD رو بده"
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

    if args.approval == "manual":
        approval_gate = ManualCLIApprovalGate()
    elif args.approval == "auto":
        approval_gate = AutoApproveGate()
    else:  # messaging — بله/تلگرام (هر کدوم که تنظیم شده باشه، هر دو هم می‌تونن هم‌زمان فعال باشن)
        notifiers = []
        telegram_token = _get_secret("telegram_token", "TELEGRAM_BOT_TOKEN")
        telegram_chat_id = _get_secret("telegram_chat_id", "TELEGRAM_CHAT_ID")
        if telegram_token and telegram_chat_id:
            notifiers.append(TelegramNotifier(token=telegram_token, chat_id=telegram_chat_id))
        bale_token = _get_secret("bale_token", "BALE_BOT_TOKEN")
        bale_chat_id = _get_secret("bale_chat_id", "BALE_CHAT_ID")
        if bale_token and bale_chat_id:
            notifiers.append(BaleNotifier(token=bale_token, chat_id=bale_chat_id))
        if not notifiers:
            logger.error("هیچ توکن تلگرام/بله تنظیم نشده — از داشبورد یا GitHub Secrets تنظیمشون کن")
            sys.exit(1)
        approval_gate = MessagingApprovalGate(notifier=CompositeNotifier(notifiers))

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

    # پوزیشن‌های باز/سرمایهٔ چرخه‌های قبلی از دیتابیس برگردونده می‌شن — بدون این،
    # هر اجرای --once از صفر شروع می‌کرد و پوزیشن‌های باز هیچ‌وقت برای SL/TP چک نمی‌شدن.
    runner.restore_state()

    if args.once:
        logger.info("اجرای یک چرخه (--once) — برای GitHub Actions/cron")
        runner.run_once()
        storage.close()
        return

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
