from __future__ import annotations

from nobitex_bot.notifications.base import TelegramLikeNotifier


class BaleNotifier(TelegramLikeNotifier):
    """⚠️ آدرس API بله بر اساس دانش عمومی گذاشته شده (`tapi.bale.ai`) و از این
    sandbox قابل‌تایید نبود (دسترسی شبکه به دامنه‌های خارج از allowlist مسدوده).
    قبل از استفادهٔ واقعی، آدرس رو از مستندات رسمی ربات بله (بله بازار /
    developers.bale.ai) verify کن — فقط همین یک ثابت رو باید عوض کنی."""

    name = "bale"
    api_base_url = "https://tapi.bale.ai"
