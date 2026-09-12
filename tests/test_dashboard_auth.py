"""تست‌های لایهٔ احراز هویت داشبورد (فاز ۹).

سه چیز این‌جا تست می‌شه که هیچ‌کدوم قبلاً وجود نداشتن:
۱. محدودیت تعداد تلاش ناموفق (جلوگیری از brute-force)
۲. نگهداری session سمت سرور — رمز اصلی نباید توی کوکی مرورگر بره
۳. ورود دومرحله‌ای با TOTP و کدهای بازیابی
"""

import pytest

from nobitex_bot.dashboard.auth import (
    LoginThrottle,
    ServerSessionStore,
    generate_recovery_codes,
    hash_recovery_code,
    verify_recovery_code,
)


class FakeClock:
    """ساعت قابل کنترل — تا تست‌ها مجبور نباشن واقعاً صبر کنن."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ---------- محدودیت تلاش ناموفق ----------


def test_throttle_allows_attempts_below_the_limit():
    throttle = LoginThrottle(max_attempts=5, lockout_seconds=900, clock=FakeClock())

    for _ in range(4):
        throttle.record_failure("1.2.3.4")

    assert throttle.is_locked("1.2.3.4") is False


def test_throttle_locks_after_reaching_the_limit():
    throttle = LoginThrottle(max_attempts=5, lockout_seconds=900, clock=FakeClock())

    for _ in range(5):
        throttle.record_failure("1.2.3.4")

    assert throttle.is_locked("1.2.3.4") is True


def test_throttle_lock_expires_after_the_lockout_window():
    clock = FakeClock()
    throttle = LoginThrottle(max_attempts=5, lockout_seconds=900, clock=clock)
    for _ in range(5):
        throttle.record_failure("1.2.3.4")

    clock.advance(901)

    assert throttle.is_locked("1.2.3.4") is False


def test_throttle_tracks_each_address_separately():
    """قفل شدن یک IP نباید بقیه رو هم قفل کنه."""
    throttle = LoginThrottle(max_attempts=5, lockout_seconds=900, clock=FakeClock())

    for _ in range(5):
        throttle.record_failure("1.2.3.4")

    assert throttle.is_locked("9.9.9.9") is False


def test_successful_login_clears_previous_failures():
    throttle = LoginThrottle(max_attempts=5, lockout_seconds=900, clock=FakeClock())
    for _ in range(4):
        throttle.record_failure("1.2.3.4")

    throttle.record_success("1.2.3.4")
    throttle.record_failure("1.2.3.4")

    assert throttle.is_locked("1.2.3.4") is False


def test_throttle_reports_remaining_lockout_seconds():
    """کاربر باید بفهمه چقدر باید صبر کنه، نه این‌که فقط رد بشه."""
    clock = FakeClock()
    throttle = LoginThrottle(max_attempts=5, lockout_seconds=900, clock=clock)
    for _ in range(5):
        throttle.record_failure("1.2.3.4")

    clock.advance(300)

    assert throttle.seconds_remaining("1.2.3.4") == 600


# ---------- session سمت سرور ----------


def test_session_store_returns_stored_payload_for_its_token():
    store = ServerSessionStore(idle_timeout_seconds=1800, clock=FakeClock())

    token = store.create({"master_password": "pw"})

    assert store.get(token) == {"master_password": "pw"}


def test_session_tokens_are_unique_per_session():
    store = ServerSessionStore(idle_timeout_seconds=1800, clock=FakeClock())

    first = store.create({"master_password": "pw"})
    second = store.create({"master_password": "pw"})

    assert first != second


def test_unknown_session_token_returns_nothing():
    store = ServerSessionStore(idle_timeout_seconds=1800, clock=FakeClock())

    assert store.get("not-a-real-token") is None


def test_session_expires_after_idle_timeout():
    clock = FakeClock()
    store = ServerSessionStore(idle_timeout_seconds=1800, clock=clock)
    token = store.create({"master_password": "pw"})

    clock.advance(1801)

    assert store.get(token) is None


def test_activity_extends_the_idle_timeout():
    """هر بار استفاده باید مهلت رو تمدید کنه، وگرنه وسط کار بیرون می‌افتی."""
    clock = FakeClock()
    store = ServerSessionStore(idle_timeout_seconds=1800, clock=clock)
    token = store.create({"master_password": "pw"})

    clock.advance(1700)
    store.get(token)
    clock.advance(1700)

    assert store.get(token) is not None


def test_destroyed_session_is_gone():
    store = ServerSessionStore(idle_timeout_seconds=1800, clock=FakeClock())
    token = store.create({"master_password": "pw"})

    store.destroy(token)

    assert store.get(token) is None


# ---------- کدهای بازیابی ----------


def test_generate_recovery_codes_returns_the_requested_count():
    codes = generate_recovery_codes(10)

    assert len(codes) == 10


def test_recovery_codes_are_all_different():
    codes = generate_recovery_codes(10)

    assert len(set(codes)) == 10


def test_recovery_code_matches_its_own_hash():
    codes = generate_recovery_codes(3)
    hashes = [hash_recovery_code(code) for code in codes]

    assert verify_recovery_code(codes[0], hashes) == hashes[0]


def test_wrong_recovery_code_matches_nothing():
    hashes = [hash_recovery_code(code) for code in generate_recovery_codes(3)]

    assert verify_recovery_code("0000-0000", hashes) is None


def test_recovery_codes_are_not_stored_in_plain_text():
    """اگه فایل رمزنگاری‌شده لو بره، کدهای بازیابی نباید مستقیم خونده بشن."""
    codes = generate_recovery_codes(1)

    assert hash_recovery_code(codes[0]) != codes[0]


# ---------- جریان ورود در Flask ----------

import re

import pyotp

from nobitex_bot.config import Settings
from nobitex_bot.dashboard.app import create_app

SECRET_PATTERN = re.compile(rb"[A-Z2-7]{32}")
RECOVERY_PATTERN = re.compile(rb"[0-9A-F]{4}-[0-9A-F]{4}")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOBITEX_DASHBOARD_USER", "kianosh")
    monkeypatch.setenv("NOBITEX_FLASK_SECRET_KEY", "test-key-not-random")
    settings = Settings(
        env="testnet",
        api_base_url="https://x",
        testnet_base_url="https://y",
        api_token="",
        data_dir=tmp_path,
        log_level="INFO",
    )
    app = create_app(settings)
    app.config.update(TESTING=True)
    return app.test_client()


def enrol(client, username="kianosh", password="pw"):
    """ورود اولیه + فعال‌سازی ۲ مرحله‌ای؛ کلید TOTP و کدهای بازیابی رو برمی‌گردونه."""
    client.post("/login", data={"username": username, "password": password})
    page = client.get("/2fa/setup")
    secret = SECRET_PATTERN.search(page.data).group().decode()
    recovery = [m.decode() for m in RECOVERY_PATTERN.findall(page.data)]
    client.post("/2fa/setup", data={"code": pyotp.TOTP(secret).now()})
    return secret, recovery


def test_login_rejects_an_unknown_username(client):
    response = client.post("/login", data={"username": "someone-else", "password": "pw"})

    assert response.status_code == 200
    assert "اشتباه".encode() in response.data


def test_login_error_does_not_reveal_which_field_was_wrong(client):
    """اگه پیام خطا فرق کنه، مهاجم می‌فهمه کدوم نام کاربری معتبره."""
    enrol(client)
    client.get("/logout")

    bad_user = client.post("/login", data={"username": "nope", "password": "pw"})
    bad_password = client.post("/login", data={"username": "kianosh", "password": "nope"})

    assert bad_user.data == bad_password.data


def test_first_login_sends_user_to_two_factor_setup(client):
    response = client.post("/login", data={"username": "kianosh", "password": "pw"})

    assert response.status_code == 302
    assert "/2fa/setup" in response.headers["Location"]


def test_dashboard_stays_locked_until_two_factor_is_completed(client):
    client.post("/login", data={"username": "kianosh", "password": "pw"})

    response = client.get("/")

    assert response.status_code == 302


def test_completing_setup_with_a_valid_code_grants_access(client):
    enrol(client)

    response = client.get("/")

    assert response.status_code == 200


def test_returning_login_requires_a_two_factor_code(client):
    enrol(client)
    client.get("/logout")

    response = client.post("/login", data={"username": "kianosh", "password": "pw"})

    assert response.status_code == 302
    assert "/2fa/verify" in response.headers["Location"]


def test_wrong_two_factor_code_is_rejected(client):
    enrol(client)
    client.get("/logout")
    client.post("/login", data={"username": "kianosh", "password": "pw"})

    response = client.post("/2fa/verify", data={"code": "000000"})

    assert client.get("/").status_code == 302
    assert "اشتباه".encode() in response.data


def test_correct_two_factor_code_grants_access(client):
    secret, _ = enrol(client)
    client.get("/logout")
    client.post("/login", data={"username": "kianosh", "password": "pw"})

    client.post("/2fa/verify", data={"code": pyotp.TOTP(secret).now()})

    assert client.get("/").status_code == 200


def test_recovery_code_works_when_the_authenticator_is_unavailable(client):
    _, recovery = enrol(client)
    client.get("/logout")
    client.post("/login", data={"username": "kianosh", "password": "pw"})

    client.post("/2fa/verify", data={"code": recovery[0]})

    assert client.get("/").status_code == 200


def test_a_recovery_code_cannot_be_used_twice(client):
    _, recovery = enrol(client)
    client.get("/logout")
    client.post("/login", data={"username": "kianosh", "password": "pw"})
    client.post("/2fa/verify", data={"code": recovery[0]})
    client.get("/logout")

    client.post("/login", data={"username": "kianosh", "password": "pw"})
    client.post("/2fa/verify", data={"code": recovery[0]})

    assert client.get("/").status_code == 302


def test_master_password_never_reaches_the_browser_cookie(client):
    """رمز اصلی کلید رمزگشایی توکن API است — نباید از سرور خارج بشه."""
    enrol(client, password="super-secret-pw")

    jar = "".join(str(cookie.value) for cookie in client._cookies.values())

    assert "super-secret-pw" not in jar


def test_account_locks_after_repeated_failures(client):
    enrol(client)
    client.get("/logout")

    for _ in range(5):
        client.post("/login", data={"username": "kianosh", "password": "wrong"})
    response = client.post("/login", data={"username": "kianosh", "password": "pw"})

    assert "قفل".encode() in response.data


def test_setup_page_renders_a_scannable_qr_code(client):
    """بدون بارکد، کاربر باید کلید ۳۲ کاراکتری رو دستی تایپ کنه."""
    client.post("/login", data={"username": "kianosh", "password": "pw"})

    page = client.get("/2fa/setup")

    assert b"<svg" in page.data
