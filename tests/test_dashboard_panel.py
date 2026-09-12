"""پنل معاملات کاغذی (سشن D، T6): API داده و صفحه."""

import json
import time
from decimal import Decimal

import pytest

from nobitex_bot.config import Settings
from nobitex_bot.dashboard.app import create_app
from nobitex_bot.data.storage import Storage
from nobitex_bot.exchange.models import Candle
from tests.test_dashboard_auth import enrol


@pytest.fixture
def panel(tmp_path, monkeypatch):
    monkeypatch.setenv("NOBITEX_DASHBOARD_USER", "kianosh")
    monkeypatch.setenv("NOBITEX_FLASK_SECRET_KEY", "test-key-not-random")
    config = {
        "profiles": {"loose": {"description": "راحت", "sources": [{"strategy": "ema21_side", "resolution": "5"}]}},
        "portfolios": [
            {"name": "loose-long", "profile": "loose", "direction": "long", "version": 1, "initial_capital_rial": 100000000}
        ],
    }
    path = tmp_path / "portfolios.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("NOBITEX_PORTFOLIOS_PATH", str(path))
    settings = Settings(
        env="testnet", api_base_url="https://x", testnet_base_url="https://y", api_token="", data_dir=tmp_path, log_level="INFO"
    )
    app = create_app(settings)
    app.config.update(TESTING=True)
    return app.test_client(), settings


def _seed(settings):
    storage = Storage(settings.data_dir / "paper_trading.sqlite")
    storage.open_paper_trade(
        "BTCIRT", "ema21_side", "5", "buy", 1000, Decimal("100"), Decimal("20000000"), "ورود آزمایشی",
        stop_loss=Decimal("98"), take_profit=Decimal("104"), portfolio="loose-long@v1",
    )
    closed = storage.open_paper_trade(
        "ETHIRT", "ema21_side", "5", "sell", 900, Decimal("50"), Decimal("20000000"), "r",
        stop_loss=Decimal("51"), take_profit=Decimal("48"), portfolio="loose-long@v1",
    )
    storage.close_paper_trade(closed, 950, Decimal("48"), Decimal("100000"), Decimal("700000"), "tp")
    # معاملهٔ آزمایش قدیمی بدون سبد نباید در پنل بیاید
    storage.open_paper_trade("XRPIRT", "breakout_atr", "60", "buy", 800, Decimal("1"), Decimal("1"), "v0")
    storage.record_equity_snapshot("loose-long@v1", 950, Decimal("100700000"), Decimal("100700000"), 0)
    price = Decimal("100")
    storage.upsert_candles(
        "BTCIRT", "5", [Candle(timestamp=int(time.time()) - 300, open=price, high=price, low=price, close=price, volume=Decimal("1"))]
    )
    storage.close()
    (settings.data_dir / "live_prices.json").write_text(
        json.dumps({"updated_at": 1, "prices": {"BTCIRT": {"latest": "103", "bid": "102", "ask": "104"}}}), encoding="utf-8"
    )


def test_panel_api_requires_login(panel):
    client, _ = panel
    assert client.get("/api/overview").status_code == 302
    assert client.get("/api/candles?symbol=BTCIRT&resolution=5").status_code == 302


def test_overview_reports_each_portfolio_with_live_unrealized_pnl(panel):
    client, settings = panel
    _seed(settings)
    enrol(client)

    body = client.get("/api/overview").get_json()

    [portfolio] = body["portfolios"]
    assert (portfolio["label"], portfolio["title"]) == ("loose-long@v1", "راحت · فقط خرید")
    assert (portfolio["closed_count"], portfolio["open_count"]) == (1, 1)
    # خرید در ۱۰۰ و bid زنده ۱۰۲ یعنی ۲٪ روی ۲۰ میلیون ریال
    assert portfolio["unrealized"] == 400000.0
    assert portfolio["equity"] == 100000000 + 700000 + 400000
    [row] = body["open_positions"]
    assert (row["symbol"], row["price"], row["unrealized"]) == ("BTCIRT", 102.0, 400000.0)
    assert [t["symbol"] for t in body["closed_trades"]] == ["ETHIRT"]


def test_candles_endpoint_returns_chart_data_and_position_levels(panel):
    client, settings = panel
    _seed(settings)
    enrol(client)

    body = client.get("/api/candles?symbol=BTCIRT&resolution=5").get_json()

    assert body["quote"] == "IRT"
    assert len(body["candles"]) == 1
    assert (body["open"][0]["stop_loss"], body["open"][0]["take_profit"]) == (98.0, 104.0)


def test_candles_endpoint_rejects_bad_input(panel):
    client, _ = panel
    enrol(client)
    assert client.get("/api/candles?symbol=../etc&resolution=5").status_code == 400
    assert client.get("/api/candles?symbol=BTCIRT&resolution=7").status_code == 400


def test_panel_page_shows_navigation_after_login(panel):
    """نوار ناوبری با session['master_password'] نشان داده می‌شد که دیگر در کوکی نیست — هیچ‌وقت دیده نمی‌شد."""
    client, _ = panel
    enrol(client)

    html = client.get("/").get_data(as_text=True)

    assert "خروج" in html
    assert 'id="equity-chart"' in html and "panel.js" in html
