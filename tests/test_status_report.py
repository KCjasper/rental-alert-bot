from datetime import UTC, datetime, timedelta
from pathlib import Path

from rental_alert_bot.database import Database
from rental_alert_bot.listing import RentalListing
from rental_alert_bot.repository import RentalRepository
from rental_alert_bot.status_report import build_monitor_status

NOW = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)


def listing(listing_id: str) -> RentalListing:
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
    )


def repository(path: Path) -> tuple[Database, RentalRepository]:
    database = Database(path)
    database.initialize()
    return database, RentalRepository(database, clock=lambda: NOW)


def create_subscription(repo: RentalRepository, region: int):
    subscription = repo.create_subscription(
        name=f"測試 {region}",
        source_url=f"https://rent.591.com.tw/list?region={region}",
        normalized_url=f"https://rent.591.com.tw/list?region={region}&sort=posttime",
    )
    return repo.activate_subscription(subscription.id)


def test_build_monitor_status_counts_operational_state(tmp_path: Path) -> None:
    database, repo = repository(tmp_path / "rental.db")
    active_due = create_subscription(repo, 1)
    active_later = create_subscription(repo, 2)
    paused = create_subscription(repo, 3)
    repo.pause_subscription(paused.id)

    repo.record_check(
        active_later.id,
        result_count=1,
        succeeded=True,
        next_check_at=NOW + timedelta(minutes=5),
    )
    repo.record_discovered_listings(active_due.id, [listing("90000001")])
    repo.record_notification_failure(
        active_due.id,
        "90000001",
        error_code="telegram_error",
    )
    repo.record_discovered_listings(active_later.id, [listing("90000002")])
    repo.record_notification_success(active_later.id, "90000002")
    repo.record_monitor_run(
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        checked_count=2,
        succeeded_count=2,
        failed_count=0,
        sent_count=1,
        notification_failed_count=1,
    )

    status = build_monitor_status(database, now=NOW)

    assert status.active_subscriptions == 2
    assert status.paused_subscriptions == 1
    assert status.due_subscriptions == 1
    assert status.pending_notifications == 1
    assert status.sent_notifications == 1
    assert status.failed_notifications == 1
    assert status.latest_check_at == NOW.isoformat(timespec="microseconds")
    assert status.monitor_run_count == 1
    assert status.checked_monitor_run_count == 1
    assert status.failed_monitor_run_count == 0
    assert status.latest_monitor_run_at == (NOW + timedelta(seconds=1)).isoformat(
        timespec="microseconds"
    )
    assert "active_subscriptions=2" in status.lines()
    assert "monitor_run_count=1" in status.lines()
    assert "checked_monitor_run_count=1" in status.lines()
