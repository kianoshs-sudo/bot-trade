from unittest.mock import MagicMock

import pytest
import requests

from nobitex_bot.exchange.coinbase_public_client import CoinbasePublicClient


def make_response(status_code: int, payload=None):
    response = MagicMock()
    response.status_code = status_code
    # کوینبیس فیلدهای عددی رو به‌صورت float برمی‌گردونه، نه رشته — کلاینت با
    # parse_float=str صداش می‌زنه، پس تست هم باید همون رفتار رو شبیه‌سازی کنه.
    response.json.side_effect = lambda **kwargs: payload
    if status_code >= 400:
        def raise_for_status():
            raise requests.exceptions.HTTPError(f"{status_code} error")
        response.raise_for_status.side_effect = raise_for_status
    else:
        response.raise_for_status = MagicMock()
    return response


def test_get_candles_parses_fields_in_coinbase_order():
    # ردیف کوینبیس: [time, low, high, open, close, volume] — ترتیب با بایننس فرق داره
    session = MagicMock()
    session.get.return_value = make_response(200, [[1690000000, "99.5", "101.0", "100.5", "100.8", "12.3"]])
    client = CoinbasePublicClient(session=session)

    candles = client.get_candles("BTC-USD", "60")

    assert len(candles) == 1
    assert candles[0].timestamp == 1690000000
    assert str(candles[0].open) == "100.5"
    assert str(candles[0].low) == "99.5"
    assert str(candles[0].high) == "101.0"
    assert str(candles[0].close) == "100.8"


def test_get_candles_returns_empty_list_on_unknown_product():
    session = MagicMock()
    session.get.return_value = make_response(404)
    client = CoinbasePublicClient(session=session)

    assert client.get_candles("NOTAREALPRODUCT", "60") == []


def test_get_candles_returns_empty_list_on_network_failure():
    session = MagicMock()
    session.get.side_effect = requests.exceptions.ConnectionError("down")
    client = CoinbasePublicClient(session=session, max_retries=1)

    assert client.get_candles("BTC-USD", "60") == []


def test_get_candles_rejects_unmapped_resolution_without_network_call():
    session = MagicMock()
    client = CoinbasePublicClient(session=session)

    assert client.get_candles("BTC-USD", "180") == []
    session.get.assert_not_called()


@pytest.mark.parametrize("status_code", [429, 500])
def test_get_candles_gives_up_after_max_retries_on_transient_errors(status_code):
    session = MagicMock()
    session.get.return_value = make_response(status_code)
    client = CoinbasePublicClient(session=session, max_retries=1)

    assert client.get_candles("BTC-USD", "60") == []
    assert session.get.call_count == 2  # تلاش اول + یک retry
