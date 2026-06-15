"""Run the phase 2 live validation against three public 591 searches."""

from __future__ import annotations

from rental_alert_bot.rental_client import RentalClient
from rental_alert_bot.rental_url import normalize_rental_search_url

SEARCHES = {
    "taipei_all": "https://rent.591.com.tw/list?region=1",
    "new_taipei_homes": "https://rent.591.com.tw/list?region=3&kind=1",
    "taichung_studios": "https://rent.591.com.tw/list?region=8&kind=2",
}


def main() -> int:
    validated_listings = 0

    with RentalClient() as client:
        for name, raw_url in SEARCHES.items():
            page = client.fetch(raw_url)
            if not page.listings:
                raise RuntimeError(f"{name} returned no listings")

            sample = page.listings[:10]
            for listing in sample:
                if not listing.listing_id.isdigit():
                    raise RuntimeError(f"{name} returned an invalid listing ID")
                if listing.price_monthly <= 0:
                    raise RuntimeError(f"{name} returned an invalid price")
                if listing.url != f"https://rent.591.com.tw/{listing.listing_id}":
                    raise RuntimeError(f"{name} returned an unexpected listing URL")

            validated_listings += len(sample)
            print(
                f"{name}: total={page.total_count}, parsed={len(page.listings)}, "
                f"sampled={len(sample)}, malformed={page.malformed_count}, "
                f"url={normalize_rental_search_url(raw_url)}"
            )

    if validated_listings < 20:
        raise RuntimeError("fewer than 20 live listings were validated")

    print(f"LIVE_VALIDATION_OK sampled={validated_listings}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
