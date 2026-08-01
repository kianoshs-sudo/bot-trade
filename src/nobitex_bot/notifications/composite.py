"""ارسال هم‌زمان به چند پلتفرم اعلان (طبق تصمیم: «هر دو بله و تلگرام، قابل‌تنظیم»).

هر پلتفرم مستقل فعال/غیرفعال می‌شه (از طریق تنظیمات)؛ اگه ارسال یکی شکست
بخوره، بقیه همچنان امتحان می‌شن."""

from __future__ import annotations

import logging
from typing import Any

from nobitex_bot.notifications.base import Notifier

logger = logging.getLogger(__name__)


class CompositeNotifier(Notifier):
    name = "composite"

    def __init__(self, notifiers: list[Notifier]) -> None:
        self.notifiers = notifiers

    def send_message(self, text: str) -> bool:
        if not self.notifiers:
            logger.warning("هیچ notifier فعالی تنظیم نشده — پیام ارسال نشد")
            return False
        return any(n.send_message(text) for n in self.notifiers)

    def get_updates(self, offset: int | None = None) -> list[dict[str, Any]]:
        updates: list[dict[str, Any]] = []
        for n in self.notifiers:
            updates.extend(n.get_updates(offset))
        return updates
