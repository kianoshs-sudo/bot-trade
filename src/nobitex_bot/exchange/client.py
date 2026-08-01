"""کلاینت HTTP برای API نوبیتکس.

- مقادیر پولی با ``Decimal`` پارس می‌شن (نه float)
- به Rate Limit مستندشده احترام گذاشته می‌شه؛ در ۴۲۹ دقیقاً به backOff صبر می‌کنه
- خطای شبکه/سرور (۵xx) با exponential backoff دوباره امتحان می‌شه
- endpointهای نیازمند توکن بدون NOBITEX_API_TOKEN اجرا نمی‌شن
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any

import requests

from nobitex_bot.config import Settings, get_settings
from nobitex_bot.exchange.endpoints import (
    ALLOWED_RESOLUTIONS,
    FORBIDDEN_RESOLUTIONS,
    MARKET_STATS,
    MINUTE_CANDLE_EPOCH_START,
    ORDERBOOK_V3,
    ORDERS_ADD,
    ORDERS_CANCEL_OLD,
    ORDERS_LIST,
    ORDERS_STATUS,
    ORDERS_UPDATE_STATUS,
    RATE_LIMITS,
    UDF_HISTORY,
    USER_TRADES_LIST,
    Endpoint,
)
from nobitex_bot.exchange.models import Candle, MarketStat, OrderBook
from nobitex_bot.exchange.rate_limiter import RateLimiter, RateLimitExceededError

logger = logging.getLogger(__name__)


class NobitexAPIError(Exception):
    """پاسخ نوبیتکس status: failed برگردونده (کد/پیام مشخص)."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class NobitexClient:
    def __init__(
        self,
        settings: Settings | None = None,
        rate_limiter: RateLimiter | None = None,
        session: requests.Session | None = None,
        max_retries: int = 5,
    ) -> None:
        self.settings = settings or get_settings()
        self.session = session or requests.Session()
        self.rate_limiter = rate_limiter or RateLimiter()
        for name, (max_calls, period) in RATE_LIMITS.items():
            self.rate_limiter.configure(name, max_calls, period)
        self.max_retries = max_retries

    def _headers(self) -> dict[str, str]:
        if self.settings.api_token:
            return {"Authorization": f"Token {self.settings.api_token}"}
        return {}

    def _request(
        self,
        endpoint: Endpoint,
        *,
        path_params: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if endpoint.requires_token and not self.settings.api_token:
            raise RuntimeError(
                f"endpoint {endpoint.path} نیاز به NOBITEX_API_TOKEN داره (در .env تنظیم کن)"
            )

        path = endpoint.path.format(**(path_params or {}))
        url = f"{self.settings.base_url}{path}"

        attempt = 0
        while True:
            self.rate_limiter.acquire(endpoint.rate_limit_bucket)
            try:
                response = self.session.request(
                    endpoint.method.value,
                    url,
                    params=params,
                    json=json_body,
                    headers=self._headers(),
                    timeout=15,
                )
            except requests.RequestException as exc:
                attempt += 1
                if attempt > self.max_retries:
                    raise
                backoff = min(2**attempt, 30)
                logger.warning(
                    "خطای شبکه در %s: %s — %d ثانیه صبر و retry (%d/%d)",
                    url, exc, backoff, attempt, self.max_retries,
                )
                time.sleep(backoff)
                continue

            if response.status_code == 429:
                attempt += 1
                if attempt > self.max_retries:
                    raise RateLimitExceededError(
                        f"حتی بعد از {self.max_retries} تلاش همچنان 429 دریافت می‌شود: {url}"
                    )
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                back_off = float(body.get("backOff", min(2**attempt, 30)))
                RateLimiter.sleep_for_backoff(back_off)
                continue

            if response.status_code >= 500:
                attempt += 1
                if attempt > self.max_retries:
                    response.raise_for_status()
                backoff = min(2**attempt, 30)
                logger.warning(
                    "خطای سرور %d در %s — %d ثانیه صبر و retry (%d/%d)",
                    response.status_code, url, backoff, attempt, self.max_retries,
                )
                time.sleep(backoff)
                continue

            response.raise_for_status()
            data = response.json(parse_float=Decimal)
            if isinstance(data, dict) and data.get("status") == "failed":
                raise NobitexAPIError(data.get("code", "Unknown"), data.get("message", ""))
            return data

    # ------------------------------------------------------------------
    # فاز ۱ — endpointهای عمومی (بدون نیاز به توکن)
    # ------------------------------------------------------------------

    def get_market_stats(
        self, src_currency: str | None = None, dst_currency: str | None = None
    ) -> dict[str, MarketStat]:
        """آمار لحظه‌ای همهٔ بازارها (یا یک بازار خاص در صورت مشخص‌کردن آرگومان‌ها)."""
        params: dict[str, Any] = {}
        if src_currency:
            params["srcCurrency"] = src_currency
        if dst_currency:
            params["dstCurrency"] = dst_currency
        data = self._request(MARKET_STATS, params=params or None)
        stats = data.get("stats", {})
        return {symbol: MarketStat.from_api(symbol, s) for symbol, s in stats.items()}

    def get_ohlc_history(
        self, symbol: str, resolution: str, from_ts: int, to_ts: int
    ) -> list[Candle]:
        """دادهٔ OHLC تاریخی. resolution باید >=5 دقیقه باشه (اسکالپ ممنوع)."""
        if resolution in FORBIDDEN_RESOLUTIONS:
            raise ValueError(
                f"resolution={resolution} مجاز نیست — طبق سند پروژه اسکالپ ممنوعه (حداقل 5 دقیقه)"
            )
        if resolution not in ALLOWED_RESOLUTIONS:
            raise ValueError(f"resolution نامعتبر: {resolution}. مقادیر مجاز: {ALLOWED_RESOLUTIONS}")

        if resolution.isdigit() and int(resolution) < 60 and from_ts < MINUTE_CANDLE_EPOCH_START:
            logger.info(
                "کندل‌های دقیقه‌ای فقط از ابتدای ۱۴۰۱ در دسترسن — from به %d تنظیم شد",
                MINUTE_CANDLE_EPOCH_START,
            )
            from_ts = max(from_ts, MINUTE_CANDLE_EPOCH_START)

        params = {"symbol": symbol, "resolution": resolution, "from": from_ts, "to": to_ts}
        data = self._request(UDF_HISTORY, params=params)
        if data.get("s") != "ok":
            return []

        candles = []
        for t, o, h, l, c, v in zip(
            data["t"], data["o"], data["h"], data["l"], data["c"], data["v"], strict=True
        ):
            candles.append(
                Candle(
                    timestamp=int(t),
                    open=Decimal(str(o)),
                    high=Decimal(str(h)),
                    low=Decimal(str(l)),
                    close=Decimal(str(c)),
                    volume=Decimal(str(v)),
                )
            )
        return candles

    def get_orderbook(self, symbol: str = "all") -> dict[str, OrderBook] | OrderBook:
        """اردربوک زنده. symbol='all' برای دریافت یکجای همهٔ بازارها (کاهش تعداد درخواست)."""
        data = self._request(ORDERBOOK_V3, path_params={"symbol": symbol})
        if symbol == "all":
            result = {}
            for key, value in data.items():
                if not isinstance(value, dict) or "bids" not in value:
                    continue
                result[key] = OrderBook.from_api(key, value)
            return result
        return OrderBook.from_api(symbol, data)

    def get_user_recent_trades(self) -> list[dict[str, Any]]:
        """معاملات ۳ روز اخیر کاربر (نیاز به توکن)."""
        data = self._request(USER_TRADES_LIST)
        return data.get("trades", [])

    # ------------------------------------------------------------------
    # فاز ۶/۷ — ثبت و مدیریت سفارش (نیاز به توکن، فقط روی Testnet تا فاز ۷)
    #
    # ⚠️ فقط خلاصهٔ prompt در دسترس بوده، نه schema کامل رسمی این endpointها.
    # نام فیلدهای body زیر بر اساس رایج‌ترین قرارداد شناخته‌شدهٔ API نوبیتکس
    # ساخته شدن، ولی قبل از فاز ۶ (تست واقعی روی Testnet) حتماً باید در برابر
    # پاسخ واقعی verify بشن. ``extra_params`` برای فیلدهای اختصاصی OCO/stop
    # (مثل stopPrice, mode) که در خلاصهٔ prompt جزئیاتشون نیومده، در نظر
    # گرفته شده تا اصلاح احتمالی بدون تغییر امضای تابع ممکن باشه.
    # ------------------------------------------------------------------

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        amount: Decimal,
        price: Decimal | None = None,
        client_order_id: str | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """ثبت سفارش. amount/price طبق الزام پروژه به‌صورت رشته ارسال می‌شن.

        side: "buy" | "sell"
        order_type: "limit" | "market" | "stop_limit" | "stop_market" | "oco"
        """
        body: dict[str, Any] = {
            "type": side,
            "execution": order_type,
            "symbol": symbol,
            "amount": str(amount),
        }
        if price is not None:
            body["price"] = str(price)
        if client_order_id is not None:
            body["clientOrderId"] = client_order_id
        if extra_params:
            body.update({k: (str(v) if isinstance(v, Decimal) else v) for k, v in extra_params.items()})
        return self._request(ORDERS_ADD, json_body=body)

    def get_order_status(self, order_id: int | None = None, client_order_id: str | None = None) -> dict[str, Any]:
        if order_id is None and client_order_id is None:
            raise ValueError("باید order_id یا client_order_id مشخص بشه")
        body: dict[str, Any] = {}
        if order_id is not None:
            body["id"] = order_id
        if client_order_id is not None:
            body["clientOrderId"] = client_order_id
        return self._request(ORDERS_STATUS, json_body=body)

    def cancel_order(self, order_id: int | None = None, client_order_id: str | None = None) -> dict[str, Any]:
        if order_id is None and client_order_id is None:
            raise ValueError("باید order_id یا client_order_id مشخص بشه")
        body: dict[str, Any] = {"status": "canceled"}
        if order_id is not None:
            body["order"] = order_id
        if client_order_id is not None:
            body["clientOrderId"] = client_order_id
        return self._request(ORDERS_UPDATE_STATUS, json_body=body)

    def cancel_old_orders(self, **filters: Any) -> dict[str, Any]:
        """لغو دسته‌جمعی سفارش‌های فعال — برای پاک‌سازی اضطراری سفارش‌های معلق."""
        return self._request(ORDERS_CANCEL_OLD, json_body=filters or None)

    def list_orders(self, **filters: Any) -> dict[str, Any]:
        return self._request(ORDERS_LIST, params=filters or None)
