"""رابط پایهٔ اعلان‌رسانی — پیاده‌سازی بله و تلگرام هر دو از این ارث می‌برن
چون API بات هر دو پلتفرم عملاً یک schema مشترک (سبک Telegram Bot API) دارن."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import requests

logger = logging.getLogger(__name__)


class Notifier(ABC):
    name: str

    @abstractmethod
    def send_message(self, text: str) -> bool:
        """پیام متنی می‌فرسته. True یعنی موفق."""

    @abstractmethod
    def get_updates(self, offset: int | None = None) -> list[dict[str, Any]]:
        """پیام‌های جدید (برای تشخیص پاسخ تایید/رد کاربر) رو برمی‌گردونه."""


class TelegramLikeNotifier(Notifier):
    """پایهٔ مشترک بله/تلگرام — هر دو از یک API سبک Telegram Bot پیروی می‌کنن،
    فقط base URL فرق داره."""

    api_base_url: str = ""

    def __init__(self, token: str, chat_id: str, timeout: int = 10) -> None:
        self.token = token
        self.chat_id = chat_id
        self.timeout = timeout

    def _url(self, method: str) -> str:
        return f"{self.api_base_url}/bot{self.token}/{method}"

    def send_message(self, text: str) -> bool:
        try:
            response = requests.post(
                self._url("sendMessage"), json={"chat_id": self.chat_id, "text": text}, timeout=self.timeout
            )
            response.raise_for_status()
            return True
        except requests.RequestException as exc:
            # پیام خطای HTTPError خودش شامل توضیح تلگرام نیست (فقط کد وضعیت)،
            # ولی بدنهٔ پاسخ معمولاً دلیل دقیق رو می‌گه (مثلاً «chat not found»
            # یا «bot was blocked by the user») — بدون این، فقط کد ۴۰۳/۴۰۰
            # می‌دیدیم و باید حدس می‌زدیم دلیلش چیه.
            body_desc = None
            response_obj = getattr(exc, "response", None)
            if response_obj is not None:
                try:
                    body_desc = response_obj.json().get("description")
                except ValueError:
                    body_desc = response_obj.text[:200] if response_obj.text else None
            logger.error(
                "ارسال پیام از طریق %s ناموفق بود (chat_id=%s): %s — توضیح تلگرام: %s",
                self.name, self.chat_id, exc, body_desc,
            )
            return False

    def get_updates(self, offset: int | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": 0}
        if offset is not None:
            params["offset"] = offset
        try:
            response = requests.get(self._url("getUpdates"), params=params, timeout=self.timeout)
            response.raise_for_status()
            return response.json().get("result", [])
        except requests.RequestException:
            logger.exception("دریافت پیام‌های جدید از طریق %s ناموفق بود", self.name)
            return []
