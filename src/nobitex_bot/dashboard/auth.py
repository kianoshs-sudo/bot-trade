"""لایهٔ احراز هویت داشبورد (فاز ۹) — مستقل از Flask، تا بشه جداگانه تستش کرد.

سه قطعهٔ مستقل این‌جاست:

``LoginThrottle``
    شمارش تلاش‌های ناموفق بر اساس IP و قفل کردن موقت. بدون این، چون رمز
    اصلی کوتاهه، حدس زدنش از بیرون فقط مسئلهٔ زمان بود.

``ServerSessionStore``
    نگهداری رمز اصلی در حافظهٔ سرور. قبلاً رمز مستقیم توی ``session`` فلسک
    می‌رفت، و session فلسک کوکیِ *امضاشده* است نه *رمزنگاری‌شده* — یعنی
    محتواش با یک decode ساده خونده می‌شد. حالا کوکی فقط یه توکن تصادفی
    داره و خود رمز از مرورگر بیرون نمی‌ره.

توابع کدهای بازیابی
    اگه گوشیِ حاوی اپ TOTP گم بشه، بدون این کدها راه برگشتی به داشبورد
    نیست. کدها hash شده ذخیره می‌شن، نه خام.

با ری‌استارت process همهٔ session‌ها و شمارنده‌ها پاک می‌شن — که برای یک
داشبورد تک‌کاربره رفتار درستیه (باید دوباره لاگین کنی، نه بیشتر).
"""

from __future__ import annotations

import hashlib
import secrets
import time
from typing import Callable

DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_LOCKOUT_SECONDS = 15 * 60
DEFAULT_IDLE_TIMEOUT_SECONDS = 30 * 60
DEFAULT_RECOVERY_CODE_COUNT = 10


class LoginThrottle:
    """قفل کردن موقت یک IP بعد از چند تلاش ناموفق پشت‌سرهم."""

    def __init__(
        self,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        lockout_seconds: int = DEFAULT_LOCKOUT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_attempts = max_attempts
        self._lockout_seconds = lockout_seconds
        self._clock = clock
        self._failures: dict[str, int] = {}
        self._locked_until: dict[str, float] = {}

    def is_locked(self, key: str) -> bool:
        locked_until = self._locked_until.get(key)
        if locked_until is None:
            return False
        if self._clock() >= locked_until:
            # مهلت قفل تموم شده — از صفر شروع می‌کنیم
            self._locked_until.pop(key, None)
            self._failures.pop(key, None)
            return False
        return True

    def record_failure(self, key: str) -> None:
        if self.is_locked(key):
            return
        attempts = self._failures.get(key, 0) + 1
        self._failures[key] = attempts
        if attempts >= self._max_attempts:
            self._locked_until[key] = self._clock() + self._lockout_seconds

    def record_success(self, key: str) -> None:
        self._failures.pop(key, None)
        self._locked_until.pop(key, None)

    def seconds_remaining(self, key: str) -> int:
        locked_until = self._locked_until.get(key)
        if locked_until is None:
            return 0
        return max(0, int(locked_until - self._clock()))


class ServerSessionStore:
    """نگهداری دادهٔ session سمت سرور؛ کوکی فقط توکنش رو حمل می‌کنه."""

    def __init__(
        self,
        idle_timeout_seconds: int = DEFAULT_IDLE_TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._idle_timeout_seconds = idle_timeout_seconds
        self._clock = clock
        self._sessions: dict[str, tuple[float, dict]] = {}

    def create(self, payload: dict) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = (self._clock(), dict(payload))
        return token

    def get(self, token: str) -> dict | None:
        entry = self._sessions.get(token)
        if entry is None:
            return None
        last_seen, payload = entry
        if self._clock() - last_seen > self._idle_timeout_seconds:
            del self._sessions[token]
            return None
        # هر دسترسی مهلت بی‌کاری رو تمدید می‌کنه
        self._sessions[token] = (self._clock(), payload)
        return payload

    def destroy(self, token: str) -> None:
        self._sessions.pop(token, None)


def generate_recovery_codes(count: int = DEFAULT_RECOVERY_CODE_COUNT) -> list[str]:
    """کدهای یک‌بارمصرف خوانا، برای وقتی که دسترسی به اپ TOTP از دست بره."""
    codes = []
    for _ in range(count):
        raw = secrets.token_hex(4).upper()
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def hash_recovery_code(code: str) -> str:
    """کدها تصادفی و پرآنتروپی‌ان، پس SHA-256 ساده کافیه (برخلاف رمز کاربر
    که KDF کند لازم داره)."""
    normalized = code.strip().upper().replace("-", "")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def verify_recovery_code(code: str, hashes: list[str]) -> str | None:
    """hash کد مطابق رو برمی‌گردونه تا فراخوان بتونه مصرفش کنه، وگرنه None."""
    candidate = hash_recovery_code(code)
    for stored in hashes:
        if secrets.compare_digest(candidate, stored):
            return stored
    return None
