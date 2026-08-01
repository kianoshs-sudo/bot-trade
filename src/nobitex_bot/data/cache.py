"""کش ساده با TTL کوتاه.

طبق مستندات نوبیتکس، فراخوانی‌های کمتر از ۱ ثانیه همون دادهٔ قبلی رو
برمی‌گردونن (کش سمت سرور). این کلاس همون رفتار رو سمت کلاینت هم رعایت
می‌کنه تا وقتی داریم همهٔ بازارها رو اسکن می‌کنیم، درخواست‌های تکراری در
بازهٔ چند ثانیه‌ای صرفه‌جویی بشن.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable


class TTLCache:
    def __init__(self, default_ttl_seconds: float = 2.0) -> None:
        self._default_ttl = default_ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get_or_set(self, key: str, factory: Callable[[], Any], ttl_seconds: float | None = None) -> Any:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        now = time.monotonic()
        with self._lock:
            cached = self._store.get(key)
            if cached is not None and now < cached[0]:
                return cached[1]
        value = factory()
        with self._lock:
            self._store[key] = (now + ttl, value)
        return value

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
