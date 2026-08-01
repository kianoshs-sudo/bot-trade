from __future__ import annotations

from nobitex_bot.notifications.base import TelegramLikeNotifier


class TelegramNotifier(TelegramLikeNotifier):
    name = "telegram"
    api_base_url = "https://api.telegram.org"
