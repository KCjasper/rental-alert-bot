"""HTTP client for public 591 rental search pages."""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from rental_alert_bot.listing import RentalSearchPage
from rental_alert_bot.rental_parser import (
    RentalPageBlockedError,
    RentalPageError,
    parse_rental_search_page,
)
from rental_alert_bot.rental_url import normalize_rental_search_url


class RentalFetchError(RentalPageError):
    """Raised when a 591 page cannot be fetched after safe retries."""


_DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
}


class RentalClient:
    def __init__(
        self,
        *,
        timeout_seconds: float = 20,
        max_attempts: int = 3,
        backoff_seconds: float = 1,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep
        self._client = httpx.Client(
            headers=_DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=timeout_seconds,
            transport=transport,
        )

    def __enter__(self) -> RentalClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def fetch(self, raw_url: str) -> RentalSearchPage:
        url = normalize_rental_search_url(raw_url)
        last_error: Exception | None = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._client.get(url)
            except httpx.RequestError as exc:
                last_error = exc
            else:
                if response.status_code in {403, 429}:
                    raise RentalPageBlockedError(
                        f"591 rejected the request with HTTP {response.status_code}"
                    )
                if 400 <= response.status_code < 500:
                    raise RentalFetchError(
                        f"591 returned non-retryable HTTP {response.status_code}"
                    )
                if response.status_code < 500:
                    content_type = response.headers.get("content-type", "")
                    if "text/html" not in content_type.lower():
                        raise RentalFetchError("591 response was not HTML")
                    return parse_rental_search_page(response.text)

                last_error = RentalFetchError(
                    f"591 returned retryable HTTP {response.status_code}"
                )

            if attempt < self._max_attempts:
                self._sleep(self._backoff_seconds * (2 ** (attempt - 1)))

        raise RentalFetchError("591 request failed after safe retries") from last_error
