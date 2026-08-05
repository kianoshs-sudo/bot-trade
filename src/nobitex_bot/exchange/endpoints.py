"""ثابت‌های endpoint و محدودیت‌های نرخ فراخوانی نوبیتکس.

مقادیر این فایل در برابر مستندات رسمی کامل (apidocs.nobitex.ir) که کاربر
پروژه مستقیماً متن کاملشو تهیه کرد، verify شدن (مرداد ۱۴۰۵). مواردی که
هنوز دقیق مستند نشده (مثل نرخ دقیق udf/history) با یک مقدار محافظه‌کارانهٔ
قابل‌تنظیم از طریق env مشخص شدن.
"""

from __future__ import annotations

import os
from enum import Enum


class HttpMethod(str, Enum):
    GET = "GET"
    POST = "POST"


class Endpoint:
    def __init__(self, method: HttpMethod, path: str, rate_limit_bucket: str, requires_token: bool):
        self.method = method
        self.path = path
        self.rate_limit_bucket = rate_limit_bucket
        self.requires_token = requires_token


MARKET_STATS = Endpoint(HttpMethod.GET, "/market/stats", "market_stats", requires_token=False)
UDF_HISTORY = Endpoint(HttpMethod.GET, "/market/udf/history", "udf_history", requires_token=False)
ORDERBOOK_V3 = Endpoint(HttpMethod.GET, "/v3/orderbook/{symbol}", "orderbook_v3", requires_token=False)
DEPTH_V2 = Endpoint(HttpMethod.GET, "/v2/depth/{symbol}", "depth_v2", requires_token=False)
TRADES_V2 = Endpoint(HttpMethod.GET, "/v2/trades/{symbol}", "trades_v2", requires_token=False)
USER_TRADES_LIST = Endpoint(HttpMethod.GET, "/market/trades/list", "user_trades_list", requires_token=True)

# فاز ۷ (فقط بعد از تایید صریح کاربر فعال می‌شن)
ORDERS_ADD = Endpoint(HttpMethod.POST, "/market/orders/add", "orders_add", requires_token=True)
ORDERS_STATUS = Endpoint(HttpMethod.POST, "/market/orders/status", "orders_status", requires_token=True)
ORDERS_UPDATE_STATUS = Endpoint(
    HttpMethod.POST, "/market/orders/update-status", "orders_update_status", requires_token=True
)
ORDERS_CANCEL_OLD = Endpoint(HttpMethod.POST, "/market/orders/cancel-old", "orders_cancel_old", requires_token=True)
ORDERS_LIST = Endpoint(HttpMethod.GET, "/market/orders/list", "orders_list", requires_token=True)
APIKEYS_CREATE = Endpoint(HttpMethod.POST, "/apikeys/create", "apikeys_create", requires_token=True)


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


# (نام bucket) -> (حداکثر تعداد فراخوانی, بازهٔ زمانی به ثانیه)
RATE_LIMITS: dict[str, tuple[int, float]] = {
    "market_stats": (_int_env("NOBITEX_RL_MARKET_STATS_PER_MIN", 20), 60.0),
    # مستند دقیقی برای udf/history داده نشده؛ محافظه‌کارانه هم‌سطح market_stats گرفته شده
    "udf_history": (_int_env("NOBITEX_RL_UDF_HISTORY_PER_MIN", 20), 60.0),
    "orderbook_v3": (_int_env("NOBITEX_RL_ORDERBOOK_PER_MIN", 300), 60.0),
    "depth_v2": (_int_env("NOBITEX_RL_DEPTH_PER_MIN", 300), 60.0),
    "trades_v2": (_int_env("NOBITEX_RL_TRADES_V2_PER_MIN", 60), 60.0),
    "user_trades_list": (_int_env("NOBITEX_RL_USER_TRADES_LIST_PER_MIN", 30), 60.0),
    "orders_add": (_int_env("NOBITEX_RL_ORDERS_ADD_PER_10MIN", 300), 600.0),
    "orders_status": (_int_env("NOBITEX_RL_ORDERS_STATUS_PER_MIN", 300), 60.0),
    "orders_update_status": (_int_env("NOBITEX_RL_ORDERS_UPDATE_STATUS_PER_MIN", 90), 60.0),
    "orders_cancel_old": (_int_env("NOBITEX_RL_ORDERS_CANCEL_OLD_PER_MIN", 30), 60.0),
    "orders_list": (_int_env("NOBITEX_RL_ORDERS_LIST_PER_MIN", 30), 60.0),
}

# طبق سند پروژه: اسکالپ ممنوعه — resolution=1 هیچ‌وقت نباید استفاده بشه.
ALLOWED_RESOLUTIONS: tuple[str, ...] = ("5", "15", "30", "60", "180", "240", "360", "720", "D", "2D", "3D")
FORBIDDEN_RESOLUTIONS: tuple[str, ...] = ("1",)

# مدت هر resolution به ثانیه — برای محاسبهٔ بازهٔ from/to لازم بین ماژول‌های بالاتر
RESOLUTION_SECONDS: dict[str, int] = {
    "5": 5 * 60,
    "15": 15 * 60,
    "30": 30 * 60,
    "60": 60 * 60,
    "180": 180 * 60,
    "240": 240 * 60,
    "360": 360 * 60,
    "720": 720 * 60,
    "D": 24 * 3600,
    "2D": 2 * 24 * 3600,
    "3D": 3 * 24 * 3600,
}

# کندل‌های دقیقه‌ای فقط از ابتدای سال ۱۴۰۱ (۲۰۲۲-۰۳-۲۱) به بعد در دسترسن.
MINUTE_CANDLE_EPOCH_START = 1647817200  # 1401-01-01 (تقریبی، UTC+3:30)

# قید حداقل ارزش معامله (خطای SmallOrder) — طبق مستندات
MIN_ORDER_VALUE_RLS = 3_000_000
MIN_ORDER_VALUE_TETHER = 11


def min_order_value_for_symbol(symbol: str) -> int:
    """حداقل ارزش معامله بر اساس ارز مقصد نماد (بازار ریالی یا تتری)."""
    upper = symbol.upper().replace("-", "").replace("_", "")
    if upper.endswith("USDT") or upper.endswith("TETHER"):
        return MIN_ORDER_VALUE_TETHER
    return MIN_ORDER_VALUE_RLS


def parse_symbol_to_currency_pair(symbol: str) -> tuple[str, str]:
    """نماد سبک udf/history (مثل ``BTCIRT``, ``1M_BTTIRT``, ``BTCUSDT``) رو به
    (srcCurrency, dstCurrency) سبک ثبت سفارش (مثل ``btc``, ``rls``) تبدیل
    می‌کنه — طبق مستندات رسمی، هر نماد دقیقاً با یکی از دو پسوند ``IRT``
    (بازار ریالی، کد ارز مقصد ``rls`` نه ``irt``) یا ``USDT`` تموم می‌شه.
    """
    lower = symbol.lower()
    if lower.endswith("irt"):
        return lower[: -len("irt")], "rls"
    if lower.endswith("usdt"):
        return lower[: -len("usdt")], "usdt"
    raise ValueError(f"نماد نامعتبر یا پسوند ناشناخته (باید IRT یا USDT باشه): {symbol}")


_STATS_QUOTE_TO_UDF_SUFFIX = {"rls": "IRT", "usdt": "USDT"}


def stats_symbol_to_udf_symbol(symbol: str) -> str:
    """``market/stats`` نمادها رو با فرمتی کاملاً متفاوت از ``market/udf/history``
    برمی‌گردونه — کوچک، با خط تیره بین پایه و مقصد (مثل ``btc-rls``،
    ``1m_btt-rls``، ``celr-usdt``)، نه فرمت udf (``BTCIRT``، ``1M_BTTIRT``،
    ``CELRUSDT``). بدون این تبدیل، هر درخواست کندل تاریخی با همون نمادِ خام
    stats با خطای ۴۰۰ رد می‌شه — چون udf/history اصلاً این فرمت رو نمی‌شناسه
    (این دقیقاً چیزیه که هیچ‌وقت به‌خاطر نبود دسترسی شبکه در فاز ۰-۶ روی
    Testnet واقعی verify نشده بود و در اولین اجرای واقعی کشف شد).
    """
    base_part, sep, quote_part = symbol.rpartition("-")
    if not sep:
        raise ValueError(f"فرمت نماد stats نامعتبر (بدون خط تیره): {symbol}")
    udf_suffix = _STATS_QUOTE_TO_UDF_SUFFIX.get(quote_part.lower())
    if udf_suffix is None:
        raise ValueError(f"ارز مقصد ناشناخته در نماد stats: {symbol}")

    if "_" in base_part:
        prefix, _, coin = base_part.partition("_")
        return f"{prefix.upper()}_{coin.upper()}{udf_suffix}"
    return f"{base_part.upper()}{udf_suffix}"

# قید محدودهٔ قیمت (خطای BadPrice)
MAX_PRICE_DEVIATION_RATIO = 0.30
