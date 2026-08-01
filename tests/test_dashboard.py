import pytest

from nobitex_bot.config import Settings
from nobitex_bot.dashboard.app import create_app
from nobitex_bot.risk.config_store import load_risk_config


@pytest.fixture
def app_client(tmp_path):
    settings = Settings(
        env="testnet", api_base_url="https://x", testnet_base_url="https://y", api_token="", data_dir=tmp_path, log_level="INFO"
    )
    app = create_app(settings)
    app.config.update(TESTING=True)
    return app.test_client(), settings


def test_index_redirects_to_login_when_not_authenticated(app_client):
    client, _ = app_client
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_first_login_creates_master_password_and_grants_access(app_client):
    client, _ = app_client
    response = client.post("/login", data={"password": "my-master-pw"}, follow_redirects=True)
    assert response.status_code == 200
    assert "وضعیت".encode() in response.data


def test_second_login_with_wrong_password_rejected(app_client):
    client, settings = app_client
    client.post("/login", data={"password": "correct-pw"})
    client.get("/logout")

    response = client.post("/login", data={"password": "wrong-pw"})
    assert response.status_code == 200
    assert "اشتباه".encode() in response.data


def test_settings_page_requires_login(app_client):
    client, _ = app_client
    response = client.get("/settings")
    assert response.status_code == 302


def test_save_secret_via_settings_form(app_client):
    client, _ = app_client
    client.post("/login", data={"password": "pw"})

    response = client.post(
        "/settings", data={"form_type": "secrets", "nobitex_api_token": "tok123"}, follow_redirects=True
    )

    assert response.status_code == 200
    assert "nobitex_api_token".encode() in response.data or "ذخیره".encode() in response.data


def test_save_risk_config_via_settings_form(app_client):
    client, settings = app_client
    client.post("/login", data={"password": "pw"})

    response = client.post(
        "/settings",
        data={
            "form_type": "risk",
            "risk_per_trade_pct": "3",
            "max_daily_loss_pct": "7",
            "max_concurrent_trades": "4",
            "max_price_deviation": "20",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    saved = load_risk_config(settings.data_dir / "risk_config.json")
    assert saved.risk_per_trade_pct == saved.risk_per_trade_pct  # sanity
    from decimal import Decimal

    assert saved.risk_per_trade_pct == Decimal("3") / 100
    assert saved.max_concurrent_trades == 4


def test_trades_page_renders_empty_state(app_client):
    client, _ = app_client
    client.post("/login", data={"password": "pw"})

    response = client.get("/trades")

    assert response.status_code == 200
