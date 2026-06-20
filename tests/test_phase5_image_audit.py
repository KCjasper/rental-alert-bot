import csv
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rental_alert_bot.database import Database
from rental_alert_bot.listing import RentalListing
from rental_alert_bot.phase5_image_audit import (
    export_image_audit_template,
    list_image_audit_candidates,
    summarize_image_audit_file,
)
from rental_alert_bot.repository import RentalRepository

NOW = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)


def listing(listing_id: str, *, image_url: str | None) -> RentalListing:
    return RentalListing(
        listing_id=listing_id,
        url=f"https://rent.591.com.tw/{listing_id}",
        title=f"測試房源 {listing_id}",
        price_monthly=18_500,
        location="中山區-測試路",
        category="獨立套房",
        layout="1房1廳",
        area_ping=8.5,
        floor="3F/5F",
        published_text="3分鐘內更新",
        image_url=image_url,
    )


def repository(path: Path) -> tuple[Database, RentalRepository]:
    database = Database(path)
    database.initialize()
    return database, RentalRepository(database, clock=lambda: NOW)


def create_subscription(repo: RentalRepository):
    subscription = repo.create_subscription(
        name="台北測試",
        source_url="https://rent.591.com.tw/list?region=1",
        normalized_url="https://rent.591.com.tw/list?region=1&sort=posttime",
    )
    return repo.activate_subscription(subscription.id)


def test_exports_image_audit_template_from_sent_image_notifications(
    tmp_path: Path,
) -> None:
    database, repo = repository(tmp_path / "rental.db")
    subscription = create_subscription(repo)
    repo.record_discovered_listings(
        subscription.id,
        [
            listing("90000001", image_url="https://hp1.591.com.tw/one.jpg"),
            listing("90000002", image_url=None),
        ],
    )
    repo.record_notification_success(subscription.id, "90000001")
    repo.record_notification_success(subscription.id, "90000002")

    candidates = list_image_audit_candidates(database)
    output = export_image_audit_template(database, tmp_path / "audit.csv")

    assert [candidate.listing_id for candidate in candidates] == ["90000001"]
    with output.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["listing_id"] == "90000001"
    assert rows[0]["image_url"] == "https://hp1.591.com.tw/one.jpg"
    assert rows[0]["image_matches"] == ""
    with pytest.raises(FileExistsError):
        export_image_audit_template(database, output)


def test_summarizes_completed_image_audit_file(tmp_path: Path) -> None:
    path = tmp_path / "audit.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "subscription_id",
                "listing_id",
                "title",
                "listing_url",
                "image_url",
                "sent_at",
                "image_matches",
                "notes",
            ],
        )
        writer.writeheader()
        writer.writerow({"listing_id": "1", "image_matches": "yes"})
        writer.writerow({"listing_id": "2", "image_matches": "否"})
        writer.writerow({"listing_id": "3", "image_matches": ""})

    summary = summarize_image_audit_file(path)

    assert summary.total_rows == 3
    assert summary.passed_checks == 1
    assert summary.failed_checks == 1
    assert summary.incomplete_checks == 1


def test_rejects_image_audit_file_with_missing_columns(tmp_path: Path) -> None:
    path = tmp_path / "audit.csv"
    path.write_text("listing_id,image_matches\n1,yes\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing columns"):
        summarize_image_audit_file(path)
