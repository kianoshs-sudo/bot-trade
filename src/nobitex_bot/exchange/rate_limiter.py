"""مدیریت Rate Limit نوبیتکس بر اساس محدودیت‌های واقعی مستندشده.

هر endpoint سقف مجزای خودش رو داره (sliding window). علاوه بر این، در پاسخ
HTTP 429 نوبیتکس فیلد ``backOff`` (ثانیه) برمی‌گردونه که باید دقیقاً به
همون مقدار صبر کرد، نه یک عدد ثابت حدسی — این بخش جدا از sliding window
محلی مدیریت می‌شه چون منبع آن پاسخ خود سرور است.

درسی که از issueهای rate-limit پروژه‌های مشابه (freqtrade/Hummingbot)
گرفته شده: 429های مکرر باید مثل circuit-breaker رفتار کنن (توقف موقت)، نه
فقط retry در حلقهٔ فشرده.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque

logger = logging.getLogger(__name__)


class RateLimitExceededError(Exception):
    """وقتی حتی بعد از احترام به backOff، سرور مدام 429 برمی‌گردونه."""


class RateLimiter:
    def __init__(self) -> None:
        self._limits: dict[str, tuple[int, float]] = {}
        self._buckets: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def configure(self, name: str, max_calls: int, period_seconds: float) -> None:
        self._limits[name] = (max_calls, period_seconds)
        self._buckets.setdefault(name, deque())

    def acquire(self, name: str) -> None:
        """در صورت نیاز، به‌اندازهٔ کافی صبر می‌کنه تا فراخوانی مجاز بشه (sliding window)."""
        if name not in self._limits:
            return  # bucket پیکربندی نشده = بدون محدودیت محلی
        max_calls, period = self._limits[name]

        while True:
            with self._lock:
                bucket = self._buckets[name]
                now = time.monotonic()
                while bucket and now - bucket[0] >= period:
                    bucket.popleft()
                if len(bucket) < max_calls:
                    bucket.append(now)
                    return
                sleep_for = period - (now - bucket[0])
            if sleep_for > 0:
                logger.debug("rate limit '%s' پر است، %.2f ثانیه صبر می‌شود", name, sleep_for)
                time.sleep(sleep_for)

    @staticmethod
    def sleep_for_backoff(back_off_seconds: float) -> None:
        """دقیقاً به‌اندازهٔ مقدار backOff که سرور برگردونده صبر می‌کنه."""
        logger.warning("HTTP 429 دریافت شد — %.2f ثانیه طبق backOff صبر می‌شود", back_off_seconds)
        time.sleep(back_off_seconds)
