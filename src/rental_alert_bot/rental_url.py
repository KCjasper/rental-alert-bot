"""Validation and normalization for 591 rental search URLs."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class RentalUrlError(ValueError):
    """Raised when a URL is not a supported 591 rental search URL."""


_TRACKING_PARAMETERS = {
    "fbclid",
    "from",
    "gclid",
    "source",
    "spm",
}
_PAGINATION_PARAMETERS = {"firstRow", "page"}


def _should_remove_parameter(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered.startswith("utm_")
        or lowered in {parameter.lower() for parameter in _TRACKING_PARAMETERS}
        or lowered in {parameter.lower() for parameter in _PAGINATION_PARAMETERS}
        or lowered == "sort"
    )


def normalize_rental_search_url(raw_url: str) -> str:
    candidate = raw_url.strip()
    if not candidate:
        raise RentalUrlError("591 rental search URL is required")

    parsed = urlsplit(candidate)
    if parsed.scheme.lower() != "https":
        raise RentalUrlError("591 rental search URL must use HTTPS")
    if parsed.username or parsed.password:
        raise RentalUrlError("591 rental search URL must not contain credentials")
    if parsed.hostname is None or parsed.hostname.lower() != "rent.591.com.tw":
        raise RentalUrlError("URL host must be rent.591.com.tw")
    try:
        port = parsed.port
    except ValueError as exc:
        raise RentalUrlError("591 rental search URL contains an invalid port") from exc
    if port not in {None, 443}:
        raise RentalUrlError("591 rental search URL must not use a custom port")
    if parsed.path.rstrip("/") != "/list":
        raise RentalUrlError("URL must point to the 591 rental list page")

    query_pairs = [
        (name, value)
        for name, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not _should_remove_parameter(name)
    ]

    region_values = [value for name, value in query_pairs if name.lower() == "region"]
    if not region_values or not all(value.isdigit() and int(value) > 0 for value in region_values):
        raise RentalUrlError("591 rental search URL must contain a numeric region")

    query_pairs.append(("sort", "posttime"))
    query_pairs.sort(key=lambda item: (item[0].lower(), item[1]))

    return urlunsplit(("https", "rent.591.com.tw", "/list", urlencode(query_pairs), ""))
