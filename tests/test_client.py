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
