import httpx
import pytest

from rental_alert_bot.telegram_client import TelegramApiError, TelegramClient


def test_send_message_posts_to_telegram_api() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    with TelegramClient("test-token", transport=httpx.MockTransport(handler)) as client:
        client.send_message(123456, "hello")

    assert requests[0].url.path == "/bottest-token/sendMessage"
    assert requests[0].read()
    assert b"hello" in requests[0].content


def test_get_updates_parses_message_updates() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": [
                    {
                        "update_id": 10,
                        "message": {
                            "message_id": 20,
                            "chat": {"id": 123456, "type": "private"},
                            "from": {"id": 123456, "is_bot": False, "first_name": "KC"},
                            "text": "/start",
                        },
                    }
                ],
            },
        )

    with TelegramClient("test-token", transport=httpx.MockTransport(handler)) as client:
        updates = client.get_updates(offset=9, timeout_seconds=1)

    assert updates[0].update_id == 10
    assert updates[0].message is not None
    assert updates[0].message.text == "/start"
    assert updates[0].message.from_user is not None
    assert updates[0].message.from_user.id == 123456


def test_get_updates_uses_longer_http_timeout_than_long_polling() -> None:
    observed_read_timeout: float | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_read_timeout
        observed_read_timeout = request.extensions["timeout"]["read"]
        return httpx.Response(200, json={"ok": True, "result": []})

    with TelegramClient("test-token", transport=httpx.MockTransport(handler)) as client:
        assert client.get_updates(timeout_seconds=30) == ()

    assert observed_read_timeout == 40


def test_retries_flood_control_using_retry_after() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                429,
                json={
                    "ok": False,
                    "error_code": 429,
                    "description": "Too Many Requests",
                    "parameters": {"retry_after": 3},
                },
            )
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    with TelegramClient(
        "test-token",
        transport=httpx.MockTransport(handler),
        sleep=delays.append,
    ) as client:
        client.send_message(123456, "hello")

    assert attempts == 2
    assert delays == [3]


def test_retries_server_errors_with_backoff() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(502, json={"ok": False})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    with TelegramClient(
        "test-token",
        transport=httpx.MockTransport(handler),
        sleep=delays.append,
    ) as client:
        client.send_message(123456, "hello")

    assert attempts == 3
    assert delays == [1, 2]


def test_raises_telegram_api_error_without_leaking_token() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "ok": False,
                "error_code": 400,
                "description": "Bad Request: chat not found",
            },
        )

    with (
        TelegramClient("secret-token", transport=httpx.MockTransport(handler)) as client,
        pytest.raises(TelegramApiError) as error,
    ):
        client.send_message(123456, "hello")

    assert error.value.error_code == 400
    assert "secret-token" not in str(error.value)
