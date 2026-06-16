"""Minimal Telegram Bot API client."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from rental_alert_bot.telegram_models import TelegramUpdate


class TelegramApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_code: int | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retry_after = retry_after


class TelegramClient:
    def __init__(
        self,
        token: str,
        *,
        timeout_seconds: float = 20,
        max_attempts: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not token.strip():
            raise ValueError("Telegram token is required")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

        self._base_url = f"https://api.telegram.org/bot{token}"
        self._max_attempts = max_attempts
        self._sleep = sleep
        self._client = httpx.Client(timeout=timeout_seconds, transport=transport)

    def __enter__(self) -> TelegramClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout_seconds: int = 30,
    ) -> tuple[TelegramUpdate, ...]:
        payload: dict[str, object] = {
            "timeout": timeout_seconds,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset

        result = self._request(
            "getUpdates",
            payload,
            request_timeout_seconds=timeout_seconds + 10,
        )
        return tuple(TelegramUpdate.from_api(item) for item in result)

    def send_message(self, chat_id: int, text: str) -> None:
        self._request(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": False,
            },
        )

    def _request(
        self,
        method: str,
        payload: dict[str, Any],
        *,
        request_timeout_seconds: float | None = None,
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._client.post(
                    f"{self._base_url}/{method}",
                    json=payload,
                    timeout=request_timeout_seconds,
                )
            except httpx.RequestError as exc:
                last_error = exc
            else:
                if response.status_code >= 500:
                    last_error = TelegramApiError(
                        "Telegram returned a server error",
                        error_code=response.status_code,
                    )
                    if attempt < self._max_attempts:
                        self._sleep(1 * (2 ** (attempt - 1)))
                        continue
                    raise last_error

                api_payload = self._parse_response(response)
                if api_payload.get("ok") is True:
                    return api_payload.get("result")

                error = self._api_error(api_payload)
                if error.retry_after is not None and attempt < self._max_attempts:
                    self._sleep(error.retry_after)
                    last_error = error
                    continue
                raise error

            if attempt < self._max_attempts:
                self._sleep(1 * (2 ** (attempt - 1)))

        raise TelegramApiError("Telegram request failed after retries") from last_error

    @staticmethod
    def _parse_response(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise TelegramApiError(
                "Telegram returned a non-JSON response",
                error_code=response.status_code,
            ) from exc

        if not isinstance(payload, dict):
            raise TelegramApiError("Telegram returned an invalid response")
        return payload

    @staticmethod
    def _api_error(payload: dict[str, Any]) -> TelegramApiError:
        parameters = payload.get("parameters")
        retry_after = None
        if isinstance(parameters, dict) and parameters.get("retry_after") is not None:
            retry_after = int(parameters["retry_after"])

        return TelegramApiError(
            str(payload.get("description", "Telegram API request failed")),
            error_code=int(payload["error_code"]) if payload.get("error_code") else None,
            retry_after=retry_after,
        )
