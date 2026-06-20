from datetime import UTC, datetime, timedelta
from pathlib import Path

from rental_alert_bot.database import Database
from rental_alert_bot.listing import RentalListing
from rental_alert_bot.phase5_validation import (
    Phase5Requirements,
    validate_phase5_runtime,
)
from rental_alert_bot.repository import RentalRepository

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
        image_url="https://hp1.591.com.tw/house.jpg",
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


def test_validate_phase5_runtime_passes_when_evidence_meets_requirements(
    tmp_path: Path,
) -> None:
    database, repo = repository(tmp_path / "rental.db")
    subscription = create_subscription(repo)
    repo.record_discovered_listings(subscription.id, [listing("90000001")])
    repo.record_notification_success(subscription.id, "90000001")
    repo.record_monitor_run(
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        checked_count=1,
        succeeded_count=1,
        failed_count=0,
        sent_count=1,
        notification_failed_count=0,
    )
    repo.record_monitor_run(
        started_at=NOW + timedelta(seconds=10),
        completed_at=NOW + timedelta(seconds=20),
        checked_count=1,
        succeeded_count=1,
        failed_count=0,
        sent_count=0,
        notification_failed_count=0,
    )

    result = validate_phase5_runtime(
        database,
        requirements=Phase5Requirements(
            minimum_runtime_hours=0.001,
            minimum_monitor_runs=2,
            minimum_image_spot_checks=1,
        ),
        manual_image_spot_checks=1,
    )

    assert result.passed is True
    assert result.monitor_run_count == 2
    assert result.checked_monitor_run_count == 2
    assert result.runtime_hours > 0.001
    assert result.duplicate_sent_notification_count == 0
    assert result.image_listing_count == 1
    assert result.lines()[0] == "PHASE5_RUNTIME_VALIDATION_OK"


def test_validate_phase5_runtime_reports_missing_evidence(tmp_path: Path) -> None:
    database = Database(tmp_path / "rental.db")
    database.initialize()

    result = validate_phase5_runtime(database)

    assert result.passed is False
    assert result.monitor_run_count == 0
    assert any("checked monitor runs" in failure for failure in result.failures)
    assert any("runtime hours" in failure for failure in result.failures)
    assert result.lines()[0] == "PHASE5_RUNTIME_VALIDATION_INCOMPLETE"


def test_validate_phase5_runtime_does_not_count_idle_iterations(
    tmp_path: Path,
) -> None:
    database, repo = repository(tmp_path / "rental.db")
    repo.record_monitor_run(
        started_at=NOW,
        completed_at=NOW + timedelta(hours=8),
        checked_count=0,
        succeeded_count=0,
        failed_count=0,
        sent_count=0,
        notification_failed_count=0,
    )

    result = validate_phase5_runtime(
        database,
        requirements=Phase5Requirements(
            minimum_runtime_hours=8,
            minimum_monitor_runs=1,
            minimum_image_spot_checks=0,
        ),
    )

    assert result.passed is False
    assert result.monitor_run_count == 1
    assert result.checked_monitor_run_count == 0
    assert any("checked monitor runs 0 < 1" in failure for failure in result.failures)


def test_validate_phase5_runtime_detects_duplicate_sent_notifications(
    tmp_path: Path,
) -> None:
    database, repo = repository(tmp_path / "rental.db")
    subscription = create_subscription(repo)
    repo.record_discovered_listings(subscription.id, [listing("90000001")])
    repo.record_notification_success(subscription.id, "90000001")
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO notification_events (
                subscription_id, listing_id, status, attempt_count,
                created_at, sent_at
            ) VALUES (?, ?, 'sent', 2, ?, ?)
            """,
            (
                subscription.id,
                "90000001",
                NOW.isoformat(timespec="microseconds"),
                NOW.isoformat(timespec="microseconds"),
            ),
        )

    result = validate_phase5_runtime(
        database,
        requirements=Phase5Requirements(
            minimum_runtime_hours=0,
            minimum_monitor_runs=0,
            minimum_image_spot_checks=0,
        ),
    )

    assert result.passed is False
    assert result.duplicate_sent_notification_count == 1


def test_validate_phase5_runtime_detects_failed_image_spot_checks(
    tmp_path: Path,
) -> None:
    database, repo = repository(tmp_path / "rental.db")
    subscription = create_subscription(repo)
    repo.record_discovered_listings(subscription.id, [listing("90000001")])
    repo.record_notification_success(subscription.id, "90000001")

    result = validate_phase5_runtime(
        database,
        requirements=Phase5Requirements(
            minimum_runtime_hours=0,
            minimum_monitor_runs=0,
            minimum_image_spot_checks=1,
        ),
        manual_image_spot_checks=1,
        failed_image_spot_checks=1,
    )

    assert result.passed is False
    assert result.failed_image_spot_checks == 1
    assert any("failed image spot checks" in failure for failure in result.failures)


def test_validate_phase5_runtime_can_filter_monitor_runs_by_time_window(
    tmp_path: Path,
) -> None:
    database, repo = repository(tmp_path / "rental.db")
    old_started = NOW - timedelta(days=1)
    window_started = NOW
    window_completed = NOW + timedelta(hours=8)
    repo.record_monitor_run(
        started_at=old_started,
        completed_at=old_started + timedelta(seconds=1),
        checked_count=1,
        succeeded_count=0,
        failed_count=1,
        sent_count=0,
        notification_failed_count=0,
        status="failed",
        error_code="RuntimeError",
    )
    repo.record_monitor_run(
        started_at=window_started,
        completed_at=window_completed,
        checked_count=1,
        succeeded_count=1,
        failed_count=0,
        sent_count=0,
        notification_failed_count=0,
    )

    without_window = validate_phase5_runtime(
        database,
        requirements=Phase5Requirements(
            minimum_runtime_hours=0,
            minimum_monitor_runs=1,
            minimum_image_spot_checks=0,
        ),
    )
    with_window = validate_phase5_runtime(
        database,
        requirements=Phase5Requirements(
            minimum_runtime_hours=8,
            minimum_monitor_runs=1,
            minimum_image_spot_checks=0,
        ),
        evidence_since=window_started,
    )

    assert without_window.passed is False
    assert any("unhandled monitor failures" in failure for failure in without_window.failures)
    assert with_window.passed is True
    assert with_window.monitor_run_count == 1
    assert with_window.checked_monitor_run_count == 1
    assert with_window.runtime_hours == 8
    assert f"evidence_since={window_started.isoformat(timespec='microseconds')}" in (
        with_window.lines()
    )


def test_validate_phase5_runtime_rejects_invalid_time_window(tmp_path: Path) -> None:
    database = Database(tmp_path / "rental.db")
    database.initialize()

    try:
        validate_phase5_runtime(
            database,
            evidence_since=NOW + timedelta(seconds=1),
            evidence_until=NOW,
        )
    except ValueError as exc:
        assert "evidence_since" in str(exc)
    else:
        raise AssertionError("expected invalid time window to be rejected")
