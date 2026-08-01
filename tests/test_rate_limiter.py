import time

from nobitex_bot.exchange.rate_limiter import RateLimiter


def test_acquire_allows_up_to_max_calls_without_sleep():
    limiter = RateLimiter()
    limiter.configure("bucket", max_calls=3, period_seconds=60.0)

    start = time.monotonic()
    for _ in range(3):
        limiter.acquire("bucket")
    elapsed = time.monotonic() - start

    assert elapsed < 0.5


def test_acquire_blocks_until_window_expires():
    limiter = RateLimiter()
    limiter.configure("bucket", max_calls=1, period_seconds=0.3)

    limiter.acquire("bucket")
    start = time.monotonic()
    limiter.acquire("bucket")
    elapsed = time.monotonic() - start

    assert elapsed >= 0.25


def test_unconfigured_bucket_never_blocks():
    limiter = RateLimiter()
    start = time.monotonic()
    for _ in range(5):
        limiter.acquire("unknown_bucket")
    assert time.monotonic() - start < 0.1


def test_sleep_for_backoff_sleeps_exact_value(monkeypatch):
    slept = []
    monkeypatch.setattr(time, "sleep", lambda seconds: slept.append(seconds))

    RateLimiter.sleep_for_backoff(7.5)

    assert slept == [7.5]
