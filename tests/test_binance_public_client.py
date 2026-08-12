from unittest.mock import MagicMock

import pytest
import requests

from nobitex_bot.exchange.binance_public_client import BinancePublicClient


def make_response(status_code: int, payload=None, headers=None):
    response = MagicMock()
    response.status_code = status_code
    response.headers = headers or {}
    response.json.return_value = payload
    if status_code >= 400:
        def raise_for_status():
            raise requests.exceptions.HTTPError(f"{status_code} error")
        response.raise_for_status.side_effect = raise_for_status
    else:
        response.raise_for_status = MagicMock()
    return response


def test_get_klines_parses_decimal_from_string_fields():
    session = MagicMock()
    session.get.return_value = make_response(
        200,
        [[1690000000000, "100.5", "101.0", "99.5", "100.8", "12.3", 1690003600000, "0", 0, "0", "0", "0"]],
    )
    client = BinancePublicClient(session=session)

    candles = client.get_klines("BTCUSDT", "60")

    assert len(candles) == 1
    assert candles[0].timestamp == 1690000000
    assert str(candles[0].open) == "100.5"
    assert str(candles[0].close) == "100.8"


def test_get_klines_returns_empty_list_on_unknown_symbol():
    session = MagicMock()
    session.get.return_value = make_response(400)
    client = BinancePublicClient(session=session)

    assert client.get_klines("NOTASYMBOLUSDT", "60") == []


def test_get_klines_returns_empty_list_on_network_failure():
    session = MagicMock()
    session.get.side_effect = requests.exceptions.ConnectionError("down")
    client = BinancePublicClient(session=session, max_retries=1)

    assert client.get_klines("BTCUSDT", "60") == []


def test_get_klines_rejects_unmapped_resolution_without_network_call():
    session = MagicMock()
    client = BinancePublicClient(session=session)

    assert client.get_klines("BTCUSDT", "999") == []
    session.get.assert_not_called()


@pytest.mark.parametrize("status_code", [429, 418, 500])
def test_get_klines_gives_up_after_max_retries_on_transient_errors(status_code):
    session = MagicMock()
    session.get.return_value = make_response(status_code, headers={"Retry-After": "0"})
    client = BinancePublicClient(session=session, max_retries=1)

    assert client.get_klines("BTCUSDT", "60") == []
    assert session.get.call_count == 2  # تلاش اول + یک retry
