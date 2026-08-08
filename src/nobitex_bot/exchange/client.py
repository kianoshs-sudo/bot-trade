"""کلاینت HTTP برای API نوبیتکس.

- مقادیر پولی با ``Decimal`` پارس می‌شن (نه float)
- به Rate Limit مستندشده احترام گذاشته می‌شه؛ در ۴۲۹ دقیقاً به backOff صبر می‌کنه
- خطای شبکه/سرور (۵xx) با exponential backoff دوباره امتحان می‌شه
- دو روش احراز هویت پشتیبانی می‌شه: توکن قدیمی (``Authorization: Token``) و
  کلید API جدید (``Nobitex-Key``/``Nobitex-Signature``/``Nobitex-Timestamp``
  با امضای Ed25519) — اگه کلید API تنظیم شده باشه، اولویت با اونه.
- endpointهای نیازمند احراز هویت بدون هیچ‌کدوم از این دو، اجرا نمی‌شن
"""

from __future__ import annotations

import json as json_module
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
    parse_symbol_to_currency_pair,
)
from nobitex_bot.exchange.models import Candle, MarketStat, OrderBook
from nobitex_bot.exchange.rate_limiter import RateLimiter, RateLimitExceededError
from nobitex_bot.exchange.signing import sign_request

logger = logging.getLogger(__name__)


class NobitexAPIError(Exception):
    """پاسخ نوبیتکس status: failed برگردونده (کد/پیام مشخص)."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


# سقف امن برای مقدار backOff که سرور برمی‌گردونه — بدون این سقف، یک مقدار
# بزرگ یا غیرمنتظره از سرور می‌تونه یک اجرای ۱۵ دقیقه‌ای GitHub Actions رو
# برای مدت نامعلومی معطل نگه داره (هر تلاش تا max_retries بار).
MAX_BACKOFF_SECONDS = 60.0


class NobitexClient:
    def __init__(
        self,
        settings: Settings | None = None,
        rate_limiter: RateLimiter | None = None,
        session: requests.Session | None = None,
        max_retries: int = 5,
        base_url: str | None = None,
    ) -> None:
        """``base_url`` رو صریح بده تا این کلاینت مستقل از ``NOBITEX_ENV``
        همیشه یک محیط مشخص (مثلاً همیشه بازار واقعی برای دادهٔ قیمت، حتی
        وقتی سفارش‌ها روی Testnet ثبت می‌شن) رو صدا بزنه. اگه خالی بمونه،
        طبق ``NOBITEX_ENV`` انتخاب می‌شه (رفتار قبلی)."""
        self.settings = settings or get_settings()
        self._base_url = base_url or self.settings.base_url
        self.session = session or requests.Session()
        self.rate_limiter = rate_limiter or RateLimiter()
        for name, (max_calls, period) in RATE_LIMITS.items():
            self.rate_limiter.configure(name, max_calls, period)
        self.max_retries = max_retries

    def _has_credentials(self) -> bool:
        return bool(self.settings.api_token) or bool(self.settings.api_key and self.settings.api_secret)

    def _auth_headers(self, method: str, signed_path: str, body_str: str) -> dict[str, str]:
        headers = {"User-Agent": f"TraderBot/{self.settings.bot_name}"}
        if self.settings.api_key and self.settings.api_secret:
            # روش جدید: کلید API + امضای Ed25519 (اولویت با این نسبت به توکن قدیمی)
            timestamp = int(time.time())
            signature = sign_request(self.settings.api_secret, timestamp, method, signed_path, body_str)
            headers["Nobitex-Key"] = self.settings.api_key
            headers["Nobitex-Signature"] = signature
            headers["Nobitex-Timestamp"] = str(timestamp)
        elif self.settings.api_token:
            headers["Authorization"] = f"Token {self.settings.api_token}"
        return headers

    def _request(
        self,
        endpoint: Endpoint,
        *,
        path_params: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if endpoint.requires_token and not self._has_credentials():
            raise RuntimeError(
                f"endpoint {endpoint.path} نیاز به احراز هویت داره — NOBITEX_API_KEY/NOBITEX_API_SECRET "
                "یا NOBITEX_API_TOKEN رو در .env تنظیم کن"
            )

        path = endpoint.path.format(**(path_params or {}))
        url = f"{self._base_url}{path}"

        # امضای Ed25519 دقیقاً روی مسیر+query و بدنهٔ خام حساسه، پس همون رشته‌ای
        # که امضا می‌شه باید عیناً همون چیزی باشه که ارسال می‌شه — نه این‌که
        # requests جدا سریالایز کنه.
        query_string = requests.compat.urlencode(params, doseq=True) if params else ""
        signed_path = f"{path}?{query_string}" if query_string else path
        body_str = json_module.dumps(json_body) if json_body is not None else ""
        body_bytes = body_str.encode("utf-8") if json_body is not None else None

        attempt = 0
        while True:
            self.rate_limiter.acquire(endpoint.rate_limit_bucket)
            request_headers = self._auth_headers(endpoint.method.value, signed_path, body_str)
            if body_bytes is not None:
                request_headers["Content-Type"] = "application/json"
            try:
                response = self.session.request(
                    endpoint.method.value,
                    url,
                    params=params,
                    data=body_bytes,
                    headers=request_headers,
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
                back_off = min(float(body.get("backOff", min(2**attempt, 30))), MAX_BACKOFF_SECONDS)
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

            if 400 <= response.status_code < 500:
                # قبل از raise_for_status عمومی، بدنهٔ پاسخ رو می‌خونیم — نوبیتکس
                # روی خطاهای ۴xx معمولاً code/message توضیحی برمی‌گردونه که با
                # HTTPError عمومی (بدون بدنه) کاملاً گم می‌شد و عیب‌یابی رو
                # غیرممکن می‌کرد (دقیقاً چیزی که اولین اجرای واقعی رو کور کرد).
                try:
                    error_body = response.json()
                except ValueError:
                    error_body = {}
                if isinstance(error_body, dict) and (error_body.get("message") or error_body.get("code")):
                    raise NobitexAPIError(
                        error_body.get("code", f"HTTP{response.status_code}"), error_body.get("message", "")
                    )

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
    # فاز ۶/۷ — ثبت و مدیریت سفارش (نیاز به احراز هویت، فقط روی Testnet تا فاز ۷)
    # طبق مستندات رسمی apidocs.nobitex.ir (بخش «معامله در بازار اسپات»)
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
        برای oco حتماً باید extra_params شامل ``mode="oco"``, ``stopPrice``,
        و ``stopLimitPrice`` باشه.
        """
        src_currency, dst_currency = parse_symbol_to_currency_pair(symbol)
        body: dict[str, Any] = {
            "type": side,
            "execution": order_type,
            "srcCurrency": src_currency,
            "dstCurrency": dst_currency,
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
