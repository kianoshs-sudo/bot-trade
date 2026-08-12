from unittest.mock import MagicMock, patch

from nobitex_bot.notifications.bale import BaleNotifier
from nobitex_bot.notifications.composite import CompositeNotifier
from nobitex_bot.notifications.telegram import TelegramNotifier


def _mock_response(json_data=None, ok=True):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    if not ok:
        response.raise_for_status.side_effect = Exception("boom")
    response.json.return_value = json_data or {"result": []}
    return response


def test_telegram_send_message_success():
    notifier = TelegramNotifier(token="t", chat_id="c")
    with patch("nobitex_bot.notifications.base.requests.post", return_value=_mock_response()) as post:
        assert notifier.send_message("hello") is True
    post.assert_called_once()
    assert "api.telegram.org" in post.call_args[0][0]


def test_bale_uses_its_own_base_url():
    notifier = BaleNotifier(token="t", chat_id="c")
    with patch("nobitex_bot.notifications.base.requests.post", return_value=_mock_response()) as post:
        notifier.send_message("hi")
    assert "tapi.bale.ai" in post.call_args[0][0]


def test_send_message_failure_returns_false():
    notifier = TelegramNotifier(token="t", chat_id="c")
    import requests

    with patch("nobitex_bot.notifications.base.requests.post", side_effect=requests.RequestException("network down")):
        assert notifier.send_message("hello") is False


def test_send_message_failure_logs_telegram_error_description(caplog):
    """سناریوی واقعی تولید: تلگرام با ۴۰۳ رد کرد، ولی HTTPError خام فقط کد
    وضعیت رو داشت — بدون خوندن بدنهٔ پاسخ، هیچ‌وقت نمی‌فهمیدیم چرا (مثلاً
    chat_id اشتباهه یا کاربر بات رو بلاک کرده)."""
    import requests

    notifier = TelegramNotifier(token="t", chat_id="wrong-chat-id")

    error_response = MagicMock()
    error_response.json.return_value = {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"}
    error_response.text = '{"description": "Forbidden: bot was blocked by the user"}'
    http_error = requests.exceptions.HTTPError("403 Client Error")
    http_error.response = error_response

    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = http_error

    with patch("nobitex_bot.notifications.base.requests.post", return_value=mock_response):
        with caplog.at_level("ERROR"):
            result = notifier.send_message("test")

    assert result is False
    assert "wrong-chat-id" in caplog.text
    assert "Forbidden: bot was blocked by the user" in caplog.text


def test_get_updates_parses_result_list():
    notifier = TelegramNotifier(token="t", chat_id="c")
    payload = {"result": [{"update_id": 1, "message": {"text": "تایید"}}]}
    with patch("nobitex_bot.notifications.base.requests.get", return_value=_mock_response(payload)):
        updates = notifier.get_updates()
    assert len(updates) == 1
    assert updates[0]["message"]["text"] == "تایید"


def test_composite_notifier_sends_to_all_and_succeeds_if_any_succeed():
    ok_notifier = MagicMock()
    ok_notifier.send_message.return_value = True
    failing_notifier = MagicMock()
    failing_notifier.send_message.return_value = False

    composite = CompositeNotifier([failing_notifier, ok_notifier])

    assert composite.send_message("x") is True
    ok_notifier.send_message.assert_called_once_with("x")
    failing_notifier.send_message.assert_called_once_with("x")


def test_composite_notifier_returns_false_with_no_notifiers():
    assert CompositeNotifier([]).send_message("x") is False


def test_composite_notifier_aggregates_updates_from_all():
    n1 = MagicMock()
    n1.get_updates.return_value = [{"update_id": 1}]
    n2 = MagicMock()
    n2.get_updates.return_value = [{"update_id": 2}]

    composite = CompositeNotifier([n1, n2])

    assert composite.get_updates() == [{"update_id": 1}, {"update_id": 2}]
