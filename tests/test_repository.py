import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rental_alert_bot.database import Database
from rental_alert_bot.listing import RentalListing
from rental_alert_bot.repository import (
    DuplicateSubscriptionError,
    InvalidSubscriptionStateError,
    RentalRepository,
    RepositoryError,
    SubscriptionStatus,
)

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


def listing(listing_id: str, *, price: int = 18_500) -> RentalListing:
    return RentalListing(
        listing_id=listing_id,
        url=f"https://rent.591.com.tw/{listing_id}",
        title=f"測試房源 {listing_id}",
        price_monthly=price,
        location="中山區-測試路",
        category="獨立套房",
        layout="1房1廳",
        area_ping=8.5,
        floor="3F/5F",
        published_text="3分鐘內更新",
    )


def repository(path: Path) -> RentalRepository:
    database = Database(path)
    database.initialize()
    return RentalRepository(database, clock=lambda: NOW)


def create_subscription(repo: RentalRepository):
    return repo.create_subscription(
        name="台北測試",
        source_url="https://rent.591.com.tw/list?region=1",
        normalized_url="https://rent.591.com.tw/list?region=1&sort=posttime",
    )


def test_subscription_lifecycle_preserves_listing_history(tmp_path: Path) -> None:
    repo = repository(tmp_path / "rental.db")
    subscription = create_subscription(repo)

    assert subscription.status is SubscriptionStatus.PENDING
    assert repo.activate_subscription(subscription.id).status is SubscriptionStatus.ACTIVE
    assert repo.record_discovered_listings(subscription.id, [listing("90000001")]) == (
        "90000001",
    )

    assert repo.pause_subscription(subscription.id).status is SubscriptionStatus.PAUSED
    assert repo.list_pending_notifications(subscription.id) == ()
    assert repo.resume_subscription(subscription.id).status is SubscriptionStatus.ACTIVE
    assert len(repo.list_pending_notifications(subscription.id)) == 1

    with pytest.raises(InvalidSubscriptionStateError):
        repo.resume_subscription(subscription.id)


def test_soft_delete_hides_subscription_without_erasing_audit_data(tmp_path: Path) -> None:
    repo = repository(tmp_path / "rental.db")
    subscription = create_subscription(repo)
    repo.record_discovered_listings(subscription.id, [listing("90000001")])

    deleted = repo.delete_subscription(subscription.id)

    assert deleted.status is SubscriptionStatus.DELETED
    assert deleted.deleted_at == NOW
    assert repo.list_subscriptions() == ()
    assert repo.list_subscriptions(include_deleted=True) == (deleted,)


def test_rejects_duplicate_normalized_subscription(tmp_path: Path) -> None:
    repo = repository(tmp_path / "rental.db")
    create_subscription(repo)

    with pytest.raises(DuplicateSubscriptionError):
        create_subscription(repo)


def test_deleted_subscription_url_can_be_created_again(tmp_path: Path) -> None:
    repo = repository(tmp_path / "rental.db")
    original = create_subscription(repo)
    repo.delete_subscription(original.id)

    replacement = create_subscription(repo)

    assert replacement.id != original.id
    assert replacement.status is SubscriptionStatus.PENDING


def test_duplicate_fetch_and_restart_keep_one_pending_relation(tmp_path: Path) -> None:
    path = tmp_path / "rental.db"
    first_process = repository(path)
    subscription = create_subscription(first_process)
    first_process.activate_subscription(subscription.id)
    listings = [listing("90000001"), listing("90000002")]

    assert first_process.record_discovered_listings(subscription.id, listings) == (
        "90000001",
        "90000002",
    )
    assert first_process.record_discovered_listings(subscription.id, listings) == ()

    restarted_process = repository(path)

    pending = restarted_process.list_pending_notifications(subscription.id)
    assert [item.listing.listing_id for item in pending] == ["90000001", "90000002"]
    assert all(item.attempt_count == 0 for item in pending)


def test_repeated_fetch_notifies_each_listing_exactly_once(tmp_path: Path) -> None:
    path = tmp_path / "rental.db"
    repo = repository(path)
    subscription = create_subscription(repo)
    repo.activate_subscription(subscription.id)
    listings = [listing("90000001"), listing("90000002")]

    for _poll in range(2):
        repo.record_discovered_listings(subscription.id, listings)
        for pending in repo.list_pending_notifications(subscription.id):
            repo.record_notification_success(
                subscription.id,
                pending.listing.listing_id,
            )

    restarted_process = repository(path)
    restarted_process.record_discovered_listings(subscription.id, listings)

    assert restarted_process.list_pending_notifications(subscription.id) == ()
    for item in listings:
        assert restarted_process.notification_event_count(
            subscription.id,
            item.listing_id,
            status="sent",
        ) == 1


def test_failed_delivery_stays_pending_and_success_is_recorded_once(tmp_path: Path) -> None:
    path = tmp_path / "rental.db"
    repo = repository(path)
    subscription = create_subscription(repo)
    repo.activate_subscription(subscription.id)
    repo.record_discovered_listings(subscription.id, [listing("90000001")])

    assert (
        repo.record_notification_failure(
            subscription.id,
            "90000001",
            error_code="telegram_timeout",
        )
        == 1
    )
    pending = repo.list_pending_notifications(subscription.id)
    assert len(pending) == 1
    assert pending[0].attempt_count == 1

    assert repo.record_notification_success(subscription.id, "90000001") is True
    assert repo.record_notification_success(subscription.id, "90000001") is False

    restarted_process = repository(path)
    assert restarted_process.list_pending_notifications(subscription.id) == ()
    assert restarted_process.notification_event_count(
        subscription.id,
        "90000001",
        status="failed",
    ) == 1
    assert restarted_process.notification_event_count(
        subscription.id,
        "90000001",
        status="sent",
    ) == 1


def test_discovery_batch_rolls_back_when_any_listing_is_invalid(tmp_path: Path) -> None:
    repo = repository(tmp_path / "rental.db")
    subscription = create_subscription(repo)
    repo.activate_subscription(subscription.id)

    with pytest.raises(sqlite3.IntegrityError, match="price_monthly"):
        repo.record_discovered_listings(
            subscription.id,
            [listing("90000001"), listing("90000002", price=0)],
        )

    assert repo.list_pending_notifications(subscription.id) == ()


def test_pending_action_can_be_completed_only_once_before_expiry(tmp_path: Path) -> None:
    repo = repository(tmp_path / "rental.db")
    subscription = create_subscription(repo)
    action = repo.create_pending_action(
        subscription_id=subscription.id,
        action_type="confirm_initial_delivery",
        payload={"listing_count": 30},
        expires_at=NOW + timedelta(minutes=10),
    )

    assert action.payload == {"listing_count": 30}
    assert repo.complete_pending_action(action.id) is True
    assert repo.complete_pending_action(action.id) is False
    assert repo.get_pending_action(action.id).status == "consumed"


def test_expired_pending_action_cannot_be_completed(tmp_path: Path) -> None:
    database = Database(tmp_path / "rental.db")
    database.initialize()
    current_time = NOW
    repo = RentalRepository(database, clock=lambda: current_time)
    action = repo.create_pending_action(
        action_type="confirm_delete",
        payload={"subscription_id": 1},
        expires_at=NOW + timedelta(minutes=1),
    )
    current_time = NOW + timedelta(minutes=2)

    assert repo.complete_pending_action(action.id) is False
    assert repo.get_pending_action(action.id).status == "pending"


def test_backup_reopens_with_subscription_and_dedup_state(tmp_path: Path) -> None:
    source_path = tmp_path / "rental.db"
    repo = repository(source_path)
    subscription = create_subscription(repo)
    repo.activate_subscription(subscription.id)
    repo.record_discovered_listings(subscription.id, [listing("90000001")])
    repo.record_notification_success(subscription.id, "90000001")

    backup_path = tmp_path / "backup.db"
    Database(source_path).backup_to(backup_path)
    restored_repo = repository(backup_path)

    assert restored_repo.get_subscription(subscription.id).status is SubscriptionStatus.ACTIVE
    assert restored_repo.list_pending_notifications(subscription.id) == ()
    assert restored_repo.record_discovered_listings(
        subscription.id,
        [listing("90000001")],
    ) == ()


def test_notification_failure_requires_existing_pending_relation(tmp_path: Path) -> None:
    repo = repository(tmp_path / "rental.db")
    subscription = create_subscription(repo)

    with pytest.raises(RepositoryError, match="relation was not found"):
        repo.record_notification_failure(
            subscription.id,
            "missing",
            error_code="telegram_timeout",
        )
