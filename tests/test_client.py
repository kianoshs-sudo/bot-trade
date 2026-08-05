import json
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from nobitex_bot.config import Settings
from nobitex_bot.exchange.client import NobitexAPIError, NobitexClient
from nobitex_bot.exchange.rate_limiter import RateLimitExceededError


def make_response(status_code: int, payload: dict):
    response = MagicMock()
    response.status_code = status_code
    response.json.side_effect = lambda **kwargs: json.loads(json.dumps(payload), parse_float=kwargs.get("parse_float", float))
    response.raise_for_status = MagicMock()
    if status_code >= 400:
        def raise_for_status():
            raise __import__("requests").exceptions.HTTPError(f"{status_code} error")
        response.raise_for_status.side_effect = raise_for_status
    return response


@pytest.fixture
def settings(tmp_path):
    return Settings(
        env="production",
        api_base_url="https://fake.nobitex.test",
        testnet_base_url="https://fake-testnet.nobitex.test",
        api_token="",
        data_dir=tmp_path,
        log_level="INFO",
    )


def test_get_market_stats_parses_decimal(settings):
    session = MagicMock()
    session.request.return_value = make_response(
        200,
        {"status": "ok", "stats": {"btc-rls": {"bestSell": "123.45", "bestBuy": "123.40", "volumeSrc": "1.5", "volumeDst": "2000"}}},
    )
    client = NobitexClient(settings=settings, session=session)

    stats = client.get_market_stats()

    assert stats["btc-rls"].best_sell == Decimal("123.45")
    assert isinstance(stats["btc-rls"].best_sell, Decimal)


def test_forbidden_resolution_raises(settings):
    client = NobitexClient(settings=settings, session=MagicMock())
    with pytest.raises(ValueError):
        client.get_ohlc_history("BTCIRT", "1", 0, 100)


def test_token_required_endpoint_without_token_raises(settings):
    client = NobitexClient(settings=settings, session=MagicMock())
    with pytest.raises(RuntimeError):
        client.get_user_recent_trades()


def test_429_respects_backoff_field_then_succeeds(settings, monkeypatch):
    slept = []
    monkeypatch.setattr("nobitex_bot.exchange.rate_limiter.time.sleep", lambda s: slept.append(s))

    session = MagicMock()
    session.request.side_effect = [
        make_response(429, {"backOff": 3, "limit": 20}),
        make_response(200, {"status": "ok", "stats": {}}),
    ]
    client = NobitexClient(settings=settings, session=session)

    client.get_market_stats()

    assert slept == [3.0]
    assert session.request.call_count == 2


def test_429_backoff_from_server_is_capped_to_prevent_indefinite_hang(settings, monkeypatch):
    """اگه سرور مقدار backOff خیلی بزرگ (یا غیرمنتظره) برگردونه، نباید یک
    اجرای ۱۵ دقیقه‌ای GitHub Actions مدت نامعلومی معطل بمونه — این دقیقاً
    همون چیزیه که یک اجرای واقعی رو در عمل هنگ کرد."""
    slept = []
    monkeypatch.setattr("nobitex_bot.exchange.rate_limiter.time.sleep", lambda s: slept.append(s))

    session = MagicMock()
    session.request.side_effect = [
        make_response(429, {"backOff": 3600, "limit": 20}),
        make_response(200, {"status": "ok", "stats": {}}),
    ]
    client = NobitexClient(settings=settings, session=session)

    client.get_market_stats()

    assert slept == [60.0]


def test_api_error_raised_on_failed_status(settings):
    session = MagicMock()
    session.request.return_value = make_response(200, {"status": "failed", "code": "SmallOrder", "message": "too small"})
    client = NobitexClient(settings=settings, session=session)

    with pytest.raises(NobitexAPIError) as exc_info:
        client.get_market_stats()

    assert exc_info.value.code == "SmallOrder"


def test_exhausted_retries_on_persistent_429_raises(settings, monkeypatch):
    monkeypatch.setattr("nobitex_bot.exchange.rate_limiter.time.sleep", lambda s: None)
    session = MagicMock()
    session.request.return_value = make_response(429, {"backOff": 1})
    client = NobitexClient(settings=settings, session=session, max_retries=2)

    with pytest.raises(RateLimitExceededError):
        client.get_market_stats()


def test_authorization_token_header_used_when_only_legacy_token_set(tmp_path):
    settings = Settings(
        env="production", api_base_url="https://x", testnet_base_url="https://y",
        api_token="legacy-token-abc", data_dir=tmp_path, log_level="INFO",
    )
    session = MagicMock()
    session.request.return_value = make_response(200, {"trades": []})
    client = NobitexClient(settings=settings, session=session)

    client.get_user_recent_trades()

    headers = session.request.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Token legacy-token-abc"
    assert "Nobitex-Key" not in headers


def test_ed25519_headers_used_and_preferred_over_legacy_token(tmp_path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import base64

    raw = Ed25519PrivateKey.generate().private_bytes_raw()
    secret_b64 = base64.urlsafe_b64encode(raw).decode()

    settings = Settings(
        env="production", api_base_url="https://x", testnet_base_url="https://y",
        api_token="legacy-token-should-be-ignored", api_key="public-key-abc", api_secret=secret_b64,
        data_dir=tmp_path, log_level="INFO",
    )
    session = MagicMock()
    session.request.return_value = make_response(200, {"trades": []})
    client = NobitexClient(settings=settings, session=session)

    client.get_user_recent_trades()

    headers = session.request.call_args.kwargs["headers"]
    assert headers["Nobitex-Key"] == "public-key-abc"
    assert "Nobitex-Signature" in headers
    assert "Nobitex-Timestamp" in headers
    assert "Authorization" not in headers


def test_place_order_sends_src_dst_currency_not_symbol(tmp_path):
    settings = Settings(
        env="production", api_base_url="https://x", testnet_base_url="https://y",
        api_token="t", data_dir=tmp_path, log_level="INFO",
    )
    session = MagicMock()
    session.request.return_value = make_response(200, {"status": "ok", "order": {"id": 1}})
    client = NobitexClient(settings=settings, session=session)

    client.place_order("BTCIRT", "buy", "limit", Decimal("0.01"), Decimal("100"))

    sent_body = json.loads(session.request.call_args.kwargs["data"])
    assert sent_body["srcCurrency"] == "btc"
    assert sent_body["dstCurrency"] == "rls"
    assert "symbol" not in sent_body


def test_place_order_oco_passes_mode_and_stop_limit_price(tmp_path):
    settings = Settings(
        env="production", api_base_url="https://x", testnet_base_url="https://y",
        api_token="t", data_dir=tmp_path, log_level="INFO",
    )
    session = MagicMock()
    session.request.return_value = make_response(200, {"status": "ok", "orders": []})
    client = NobitexClient(settings=settings, session=session)

    client.place_order(
        "BTCUSDT", "sell", "oco", Decimal("0.01"), Decimal("42390"),
        extra_params={"mode": "oco", "stopPrice": Decimal("42700"), "stopLimitPrice": Decimal("42680")},
    )

    sent_body = json.loads(session.request.call_args.kwargs["data"])
    assert sent_body["mode"] == "oco"
    assert sent_body["stopPrice"] == "42700"
    assert sent_body["stopLimitPrice"] == "42680"
    assert sent_body["srcCurrency"] == "btc"
    assert sent_body["dstCurrency"] == "usdt"
