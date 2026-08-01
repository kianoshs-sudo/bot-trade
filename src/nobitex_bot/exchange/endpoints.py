"""ثابت‌های endpoint و محدودیت‌های نرخ فراخوانی نوبیتکس.

⚠️ توجه: فقط یک فایل خلاصهٔ prompt (نه مستندات کامل رسمی نوبیتکس) در
دسترس این پروژه بوده. مقادیر method/path/rate-limit این فایل دقیقاً از
همون خلاصه گرفته شدن. قبل از فاز ۷ (اجرای واقعی روی پول واقعی) حتماً این
مقادیر را در برابر مستندات رسمی کامل (docs.nobitex.ir یا مخزن رسمی
nobitex/docs-api) دوباره verify کن — مخصوصاً متد HTTP دقیق و نام فیلدهای
پاسخ که ممکنه در نسخه‌های به‌روزتر تغییر کرده باشن.

مقدار هر بخش سقف مجزای خودشه؛ برای آنهایی که در prompt عدد دقیق نداشتن
(مثل udf/history) یک مقدار محافظه‌کارانه پیش‌فرض گذاشته شده که از طریق
env قابل تغییره.
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

# کندل‌های دقیقه‌ای فقط از ابتدای سال ۱۴۰۱ (۲۰۲۲-۰۳-۲۱) به بعد در دسترسن.
MINUTE_CANDLE_EPOCH_START = 1647817200  # 1401-01-01 (تقریبی، UTC+3:30)

# قید حداقل ارزش معامله (خطای SmallOrder) — طبق مستندات
MIN_ORDER_VALUE_RLS = 3_000_000
MIN_ORDER_VALUE_TETHER = 11

# قید محدودهٔ قیمت (خطای BadPrice)
MAX_PRICE_DEVIATION_RATIO = 0.30
