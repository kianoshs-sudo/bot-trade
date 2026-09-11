#!/usr/bin/env python3
"""ارسال نمونهٔ هر سه پیام معاملاتی به بله/تلگرام — برای دیدن ظاهر واقعی‌شان.

هیچ سفارشی ثبت نمی‌شود و به هیچ endpoint معاملاتی دست نمی‌زند؛ فقط متن
می‌فرستد. توکن از همان GitHub Secrets / .env خوانده می‌شود که ربات استفاده
می‌کند، پس هیچ اعتبارنامه‌ای جابه‌جا نمی‌شود.

    python scripts/send_test_notification.py

اگر پیامی نرسید، خروجی همین اسکریپت علت دقیق تلگرام را چاپ می‌کند — برای
عیب‌یابی «بات در گروه هست ولی پیام نمی‌آید» (که معمولاً یعنی بات در گروه
ادمین نیست، یا TELEGRAM_CHAT_ID آیدی گروه نیست).
"""

from __future__ import annotations

import logging
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nobitex_bot.config import get_settings
from nobitex_bot.notifications.bale import BaleNotifier
from nobitex_bot.notifications.composite import CompositeNotifier
from nobitex_bot.notifications.messages import (
    format_order_failed_message,
    format_order_placed_message,
    format_signal_message,
    signal_ref,
)
from nobitex_bot.notifications.telegram import TelegramNotifier
from nobitex_bot.strategies.base import TradeSignal
from nobitex_bot.utils.logging import setup_logging

logger = logging.getLogger(__name__)

SAMPLE_RATE = Decimal("211000")  # ریال به ازای هر تتر، فقط برای نمونه


def build_notifier() -> CompositeNotifier | None:
    notifiers = []
    token, chat_id = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        notifiers.append(TelegramNotifier(token=token, chat_id=chat_id))
        logger.info("تلگرام فعال — chat_id=%s", chat_id)
    bale_token, bale_chat = os.environ.get("BALE_BOT_TOKEN"), os.environ.get("BALE_CHAT_ID")
    if bale_token and bale_chat:
        notifiers.append(BaleNotifier(token=bale_token, chat_id=bale_chat))
        logger.info("بله فعال — chat_id=%s", bale_chat)
    return CompositeNotifier(notifiers) if notifiers else None


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    notifier = build_notifier()
    if notifier is None:
        logger.error(
            "هیچ توکنی تنظیم نشده. TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_ID (یا معادل بله) لازم است."
        )
        sys.exit(1)

    signal = TradeSignal(
        symbol="ADAUSDT",
        direction="buy",
        entry_price_hint=Decimal("0.2054"),
        stop_loss=Decimal("0.19"),
        take_profit=Decimal("0.22"),
        reason="پیام تست — قیمت به باند پایین بولینگر رسید (close=0.2054 <= BBL=0.2061) و RSI=28.2",
        strategy_name="mean_reversion_rsi_bb",
    )
    size_quote = Decimal("13337662")  # ریال
    ref = signal_ref("7e57c0de-0000-4000-8000-000000000001")

    messages = [
        "🧪 پیام تست — سه پیام بعدی نمونهٔ پیام‌های واقعی ربات‌اند. هیچ سفارشی ثبت نشده.",
        format_signal_message(signal, size_quote, ref, SAMPLE_RATE),
        format_order_placed_message(signal, ref, size_quote / SAMPLE_RATE, "نمونه-۱۲۳۴۵"),
        format_order_failed_message(signal, ref, "HTTP401: API key is invalid."),
    ]

    failures = 0
    for i, text in enumerate(messages, 1):
        ok = notifier.send_message(text)
        logger.info("پیام %d از %d — ارسال %s", i, len(messages), "موفق" if ok else "ناموفق")
        if not ok:
            failures += 1

    if failures:
        logger.error(
            "%d پیام ارسال نشد. علت دقیق تلگرام در خطوط بالا («توضیح تلگرام: ...») آمده. "
            "رایج‌ترین علت: بات در گروه ادمین نیست، یا TELEGRAM_CHAT_ID آیدی گروه (منفی) نیست.",
            failures,
        )
        sys.exit(1)
    logger.info("همهٔ پیام‌ها ارسال شد.")


if __name__ == "__main__":
    main()
