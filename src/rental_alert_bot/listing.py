"""Rental listing domain models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RentalListing:
    listing_id: str
    url: str
    title: str
    price_monthly: int
    location: str
    category: str | None
    layout: str | None
    area_ping: float | None
    floor: str | None
    published_text: str | None
    image_url: str | None = None


@dataclass(frozen=True, slots=True)
class RentalSearchPage:
    total_count: int
    listings: tuple[RentalListing, ...]
    malformed_count: int = 0
