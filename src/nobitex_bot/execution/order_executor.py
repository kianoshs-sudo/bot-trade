"""ثبت سفارش با idempotency واقعی — درسِ فاز ۰ دربارهٔ باگ‌های سفارش تکراری.

قاعدهٔ کلیدی: ``clientOrderId`` **قبل از** ارسال درخواست HTTP تولید و در
دیتابیس محلی به‌عنوان ``pending`` ذخیره می‌شه. اگه پاسخ صرافی ``DuplicateOrder``
باشه (یعنی یک تلاش قبلی — مثلاً به‌خاطر قطعی شبکه — واقعاً ثبت شده بوده)،
به‌جای شکست، وضعیت واقعی سفارش از صرافی استعلام و با دیتابیس محلی
reconcile می‌شه؛ هیچ‌وقت سفارش دوم ارسال نمی‌شه.
"""

from __future__ import annotations

import logging
import time
import uuid
from decimal import Decimal
from typing import Any

from nobitex_bot.data.storage import Storage
from nobitex_bot.exchange.client import NobitexAPIError, NobitexClient

logger = logging.getLogger(__name__)


class OrderExecutor:
    def __init__(self, client: NobitexClient, storage: Storage) -> None:
        self.client = client
        self.storage = storage

    def submit_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        amount: Decimal,
        price: Decimal | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client_order_id = str(uuid.uuid4())
        now_ts = int(time.time())
        self.storage.record_order_intent(client_order_id, symbol, side, order_type, amount, price, now_ts)

        try:
            response = self.client.place_order(
                symbol=symbol,
                side=side,
                order_type=order_type,
                amount=amount,
                price=price,
                client_order_id=client_order_id,
                extra_params=extra_params,
            )
        except NobitexAPIError as exc:
            if exc.code == "DuplicateOrder":
                logger.warning(
                    "پاسخ DuplicateOrder برای %s — احتمالاً تلاش قبلی واقعاً ثبت شده؛ به‌جای ارسال دوباره reconcile می‌شه",
                    client_order_id,
                )
                return self._reconcile(client_order_id)
            self.storage.update_order_intent_status(
                client_order_id, "failed", int(time.time()), error_message=str(exc)
            )
            raise

        exchange_order_id = str(response.get("order", {}).get("id", "")) if isinstance(response.get("order"), dict) else None
        self.storage.update_order_intent_status(
            client_order_id, "placed", int(time.time()), exchange_order_id=exchange_order_id
        )
        return response

    def _reconcile(self, client_order_id: str) -> dict[str, Any]:
        status = self.client.get_order_status(client_order_id=client_order_id)
        exchange_order_id = str(status.get("order", {}).get("id", "")) if isinstance(status.get("order"), dict) else None
        self.storage.update_order_intent_status(
            client_order_id, "reconciled_duplicate", int(time.time()), exchange_order_id=exchange_order_id
        )
        return status
