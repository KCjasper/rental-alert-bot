from pathlib import Path

import pytest

from rental_alert_bot.rental_parser import (
    RentalPageBlockedError,
    RentalPageStructureError,
    parse_rental_search_page,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parses_listing_fields() -> None:
    page = parse_rental_search_page(fixture("591_search_normal.html"))

    assert page.total_count == 2
    assert page.malformed_count == 0
    assert len(page.listings) == 2

    first = page.listings[0]
    assert first.listing_id == "90000001"
    assert first.url == "https://rent.591.com.tw/90000001"
    assert first.title == "採光套房近捷運"
    assert first.price_monthly == 18_500
    assert first.location == "中山區-測試路"
    assert first.category == "獨立套房"
    assert first.layout == "1房1廳"
    assert first.area_ping == 8.5
    assert first.floor == "3F/5F"
    assert first.published_text == "3分鐘內更新"


def test_accepts_empty_search_results() -> None:
    page = parse_rental_search_page(fixture("591_search_empty.html"))

    assert page.total_count == 0
    assert page.listings == ()


def test_detects_page_structure_change() -> None:
    with pytest.raises(RentalPageStructureError, match="nodes were not found"):
        parse_rental_search_page(fixture("591_search_changed.html"))


def test_detects_verification_page() -> None:
    with pytest.raises(RentalPageBlockedError):
        parse_rental_search_page("<html><body>請完成人機驗證</body></html>")
