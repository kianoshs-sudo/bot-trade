from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from nobitex_bot.data.storage import Storage
from nobitex_bot.exchange.client import NobitexAPIError
from nobitex_bot.execution.order_executor import OrderExecutor


@pytest.fixture
def storage(tmp_path):
    s = Storage(tmp_path / "test.sqlite")
    yield s
    s.close()


def test_submit_order_success_records_intent_as_placed(storage):
    client = MagicMock()
    client.place_order.return_value = {"status": "ok", "order": {"id": 12345}}
    executor = OrderExecutor(client=client, storage=storage)

    response = executor.submit_order("BTCIRT", "buy", "limit", Decimal("0.01"), Decimal("100"))

    assert response["order"]["id"] == 12345
    client.place_order.assert_called_once()
    _, kwargs = client.place_order.call_args
    client_order_id = kwargs["client_order_id"]
    intent = storage.get_order_intent(client_order_id)
    assert intent["status"] == "placed"
    assert intent["exchange_order_id"] == "12345"


def test_submit_order_generates_client_order_id_before_sending(storage):
    client = MagicMock()
    client.place_order.return_value = {"status": "ok", "order": {"id": 1}}
    executor = OrderExecutor(client=client, storage=storage)

    executor.submit_order("BTCIRT", "buy", "limit", Decimal("0.01"), Decimal("100"))

    _, kwargs = client.place_order.call_args
    client_order_id = kwargs["client_order_id"]
    assert client_order_id is not None and len(client_order_id) > 0


def test_submit_order_reconciles_on_duplicate_order_instead_of_retrying(storage):
    client = MagicMock()
    client.place_order.side_effect = NobitexAPIError("DuplicateOrder", "already placed")
    client.get_order_status.return_value = {"status": "ok", "order": {"id": 999, "status": "Active"}}
    executor = OrderExecutor(client=client, storage=storage)

    response = executor.submit_order("BTCIRT", "buy", "limit", Decimal("0.01"), Decimal("100"))

    assert response["order"]["id"] == 999
    client.place_order.assert_called_once()  # هرگز دوباره ارسال نشد
    client.get_order_status.assert_called_once()


def test_submit_order_marks_failed_and_reraises_on_other_errors(storage):
    client = MagicMock()
    client.place_order.side_effect = NobitexAPIError("SmallOrder", "too small")
    executor = OrderExecutor(client=client, storage=storage)

    with pytest.raises(NobitexAPIError):
        executor.submit_order("BTCIRT", "buy", "limit", Decimal("0.001"), Decimal("100"))

    _, kwargs = client.place_order.call_args
    intent = storage.get_order_intent(kwargs["client_order_id"])
    assert intent["status"] == "failed"
