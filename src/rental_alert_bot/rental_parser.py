"""HTML parsing for public 591 rental search pages."""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from rental_alert_bot.listing import RentalListing, RentalSearchPage


class RentalPageError(RuntimeError):
    """Base error for an unusable 591 search page."""


class RentalPageBlockedError(RentalPageError):
    """Raised when the response appears to be blocked or challenged."""


class RentalPageStructureError(RentalPageError):
    """Raised when expected listing structure is missing or malformed."""


_BLOCK_MARKERS = (
    "captcha",
    "cloudflare",
    "人機驗證",
    "驗證碼",
    "存取遭拒",
)
_AREA_PATTERN = re.compile(r"(?P<area>\d+(?:\.\d+)?)\s*坪")
_BACKGROUND_IMAGE_PATTERN = re.compile(r"url\((?P<quote>['\"]?)(?P<url>.*?)(?P=quote)\)")
_PRICE_PATTERN = re.compile(r"\d[\d,]*")
_TOTAL_PATTERN = re.compile(r"\d[\d,]*")


def detect_blocked_page(html: str) -> None:
    lowered = html.lower()
    if any(marker in lowered for marker in _BLOCK_MARKERS):
        raise RentalPageBlockedError("591 returned a blocked or verification page")


def _text_values(node: Tag | None) -> list[str]:
    if node is None:
        return []
    return [value.strip() for value in node.stripped_strings if value.strip()]


def _parse_total_count(soup: BeautifulSoup) -> int | None:
    total_node = soup.select_one(".list-sort .total strong, p.total strong")
    if total_node is None:
        return None

    match = _TOTAL_PATTERN.search(total_node.get_text(strip=True))
    if match is None:
        return None
    return int(match.group(0).replace(",", ""))


def _first_matching(values: Iterable[str], pattern: re.Pattern[str]) -> str | None:
    return next((value for value in values if pattern.search(value)), None)


def _normalize_image_url(raw_url: str) -> str | None:
    value = raw_url.strip()
    if not value or value.startswith("data:"):
        return None

    if value.startswith("//"):
        value = f"https:{value}"
    elif value.startswith("/"):
        value = urljoin("https://rent.591.com.tw", value)

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return None
    host = parsed.hostname or ""
    if host != "591.com.tw" and not host.endswith(".591.com.tw"):
        return None

    return parsed._replace(scheme="https").geturl()


def _parse_image_url(item: Tag) -> str | None:
    for image in item.select("img"):
        for attribute in ("data-src", "data-original", "src"):
            raw_value = image.get(attribute)
            if isinstance(raw_value, str) and (url := _normalize_image_url(raw_value)):
                return url

    for node in item.select("[style]"):
        style = node.get("style")
        if not isinstance(style, str):
            continue
        match = _BACKGROUND_IMAGE_PATTERN.search(style)
        if match and (url := _normalize_image_url(match.group("url"))):
            return url

    return None


def _parse_listing(item: Tag) -> RentalListing:
    listing_id = item.get("data-id", "").strip()
    title_link = item.select_one(".item-info-title a.link[href]")
    price_node = item.select_one(".item-info-price strong")
    info_nodes = item.select(".item-info-txt")

    if not listing_id or title_link is None or price_node is None or len(info_nodes) < 2:
        raise RentalPageStructureError("listing is missing required nodes")

    title = title_link.get_text(" ", strip=True)
    href = title_link.get("href", "").strip()
    price_match = _PRICE_PATTERN.search(price_node.get_text(" ", strip=True))
    if not title or not href or price_match is None:
        raise RentalPageStructureError("listing is missing title, URL, or price")

    details = _text_values(info_nodes[0])
    location_values = _text_values(info_nodes[1])
    role_values = _text_values(item.select_one(".item-info-txt.role-name"))

    category = details[0] if details else None
    layout = _first_matching(details, re.compile(r"\d+\s*房"))
    area_text = _first_matching(details, _AREA_PATTERN)
    area_match = _AREA_PATTERN.search(area_text) if area_text else None
    floor = _first_matching(details, re.compile(r"(?:樓|F|地下)", re.IGNORECASE))
    location = location_values[-1] if location_values else ""
    published_text = next(
        (value for value in role_values if "更新" in value or "上架" in value),
        None,
    )

    if not location:
        raise RentalPageStructureError("listing is missing location")

    return RentalListing(
        listing_id=listing_id,
        url=href,
        title=title,
        price_monthly=int(price_match.group(0).replace(",", "")),
        location=location,
        category=category,
        layout=layout,
        area_ping=float(area_match.group("area")) if area_match else None,
        floor=floor,
        published_text=published_text,
        image_url=_parse_image_url(item),
    )


def parse_rental_search_page(html: str) -> RentalSearchPage:
    detect_blocked_page(html)
    soup = BeautifulSoup(html, "html.parser")
    total_count = _parse_total_count(soup)
    item_nodes = soup.select("div.item[data-id]")

    if not item_nodes:
        if total_count == 0:
            return RentalSearchPage(total_count=0, listings=())
        raise RentalPageStructureError("591 listing nodes were not found")

    listings: list[RentalListing] = []
    malformed_count = 0
    for item in item_nodes:
        try:
            listings.append(_parse_listing(item))
        except RentalPageStructureError:
            malformed_count += 1

    if not listings or malformed_count / len(item_nodes) > 0.2:
        raise RentalPageStructureError("too many 591 listings were malformed")

    listing_ids = [listing.listing_id for listing in listings]
    if len(listing_ids) != len(set(listing_ids)):
        raise RentalPageStructureError("591 returned duplicate listing IDs")

    return RentalSearchPage(
        total_count=total_count if total_count is not None else len(listings),
        listings=tuple(listings),
        malformed_count=malformed_count,
    )
