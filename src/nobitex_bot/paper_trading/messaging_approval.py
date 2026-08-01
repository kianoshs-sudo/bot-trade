"""دروازهٔ تاییدیه از طریق بله/تلگرام — جایگزین نهایی ``ManualCLIApprovalGate``.

به‌جای دکمهٔ inline (که schema دقیقش بین بله و تلگرام ممکنه فرق کنه و از
این sandbox قابل‌تایید نبود)، از **پاسخ متنی ساده** استفاده می‌شه («تایید»
یا «رد») — چون روی هر دو پلتفرم بدون هیچ فرضی یکسان کار می‌کنه. اگه در
مهلت مشخص‌شده پاسخی نیاد، **پیش‌فرض رده** (safe default) — یعنی بدون تایید
صریح، هیچ سفارشی ثبت نمی‌شه.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal

from nobitex_bot.notifications.base import Notifier
from nobitex_bot.paper_trading.approval import ApprovalGate
from nobitex_bot.strategies.base import TradeSignal

logger = logging.getLogger(__name__)

APPROVE_KEYWORDS = ("تایید", "تایید ✅", "ok", "yes")
REJECT_KEYWORDS = ("رد", "رد ❌", "no", "cancel")


class MessagingApprovalGate(ApprovalGate):
    def __init__(
        self,
        notifier: Notifier,
        timeout_seconds: int = 300,
        poll_interval_seconds: int = 5,
    ) -> None:
        self.notifier = notifier
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds

    def request_approval(self, signal: TradeSignal, position_size_quote: Decimal) -> bool:
        text = (
            f"سیگنال جدید — {signal.symbol} ({signal.strategy_name})\n"
            f"جهت: {signal.direction}\n"
            f"دلیل: {signal.reason}\n"
            f"ورود: {signal.entry_price_hint}   SL: {signal.stop_loss}   TP: {signal.take_profit}\n"
            f"اندازهٔ پوزیشن: {position_size_quote}\n\n"
            f"برای تایید «تایید» و برای رد «رد» رو ریپلای کن (تا {self.timeout_seconds} ثانیه)."
        )
        self.notifier.send_message(text)

        deadline = time.monotonic() + self.timeout_seconds
        last_offset: int | None = None
        while time.monotonic() < deadline:
            for update in self.notifier.get_updates(offset=last_offset):
                last_offset = update.get("update_id", 0) + 1
                message_text = (update.get("message", {}).get("text") or "").strip().lower()
                if message_text in APPROVE_KEYWORDS:
                    return True
                if message_text in REJECT_KEYWORDS:
                    return False
            time.sleep(self.poll_interval_seconds)

        logger.warning("پاسخی در مهلت %d ثانیه دریافت نشد — سیگنال به‌صورت پیش‌فرض رد شد", self.timeout_seconds)
        return False
