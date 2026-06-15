import pytest

from rental_alert_bot.rental_url import RentalUrlError, normalize_rental_search_url


def test_normalizes_search_url_and_forces_latest_sort() -> None:
    normalized = normalize_rental_search_url(
        "https://rent.591.com.tw/list?utm_source=test&kind=2&region=1&page=3#result"
    )

    assert normalized == "https://rent.591.com.tw/list?kind=2&region=1&sort=posttime"


@pytest.mark.parametrize(
    "url",
    [
        "http://rent.591.com.tw/list?region=1",
        "https://rent.591.com.tw.evil.example/list?region=1",
        "https://user@rent.591.com.tw/list?region=1",
        "https://rent.591.com.tw:8443/list?region=1",
        "https://rent.591.com.tw:invalid/list?region=1",
        "https://rent.591.com.tw/map-index.html?region=1",
        "https://rent.591.com.tw/list",
        "https://rent.591.com.tw/list?region=not-a-number",
    ],
)
def test_rejects_unsupported_urls(url: str) -> None:
    with pytest.raises(RentalUrlError):
        normalize_rental_search_url(url)


def test_preserves_repeated_search_filters() -> None:
    normalized = normalize_rental_search_url(
        "https://rent.591.com.tw/list?region=1&section=5&section=7"
    )

    assert normalized == (
        "https://rent.591.com.tw/list?region=1&section=5&section=7&sort=posttime"
    )
