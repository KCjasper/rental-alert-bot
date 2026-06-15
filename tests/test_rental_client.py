import httpx
import pytest

from rental_alert_bot.rental_client import RentalClient, RentalFetchError
from rental_alert_bot.rental_parser import RentalPageBlockedError

HTML = """
<div class="list-sort"><p class="total"><strong>1</strong></p></div>
<div class="item" data-id="90000001">
  <div class="item-info-title">
    <a class="link" href="https://rent.591.com.tw/90000001">測試房源</a>
  </div>
  <div class="item-info-txt">
    <span>獨立套房</span><span>8坪</span><span>2F/5F</span>
  </div>
  <div class="item-info-txt"><span>中山區-測試路</span></div>
  <div class="item-info-txt role-name"><span>1小時內更新</span></div>
  <div class="item-info-price"><strong>15,000</strong></div>
</div>
"""


def test_fetches_and_parses_search_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["sort"] == "posttime"
        return httpx.Response(200, text=HTML, headers={"content-type": "text/html"})

    with RentalClient(transport=httpx.MockTransport(handler)) as client:
        page = client.fetch("https://rent.591.com.tw/list?region=1")

    assert page.listings[0].listing_id == "90000001"


@pytest.mark.parametrize("status_code", [403, 429])
def test_does_not_retry_blocked_requests(status_code: int) -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status_code, text="blocked")

    with (
        RentalClient(
            transport=httpx.MockTransport(handler),
            sleep=lambda _delay: None,
        ) as client,
        pytest.raises(RentalPageBlockedError),
    ):
        client.fetch("https://rent.591.com.tw/list?region=1")

    assert attempts == 1


def test_retries_server_errors_with_exponential_backoff() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, text="unavailable")

    with RentalClient(
        transport=httpx.MockTransport(handler),
        backoff_seconds=2,
        sleep=delays.append,
    ) as client, pytest.raises(RentalFetchError, match="safe retries"):
        client.fetch("https://rent.591.com.tw/list?region=1")

    assert attempts == 3
    assert delays == [2, 4]


def test_rejects_non_html_response() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={"data": []},
            headers={"content-type": "application/json"},
        )
    )

    with (
        RentalClient(transport=transport) as client,
        pytest.raises(RentalFetchError, match="not HTML"),
    ):
        client.fetch("https://rent.591.com.tw/list?region=1")
