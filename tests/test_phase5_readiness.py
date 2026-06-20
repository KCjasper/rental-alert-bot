from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rental_alert_bot.database import Database
from rental_alert_bot.phase5_readiness import check_phase5_readiness
from rental_alert_bot.phase5_validation import Phase5Requirements
from rental_alert_bot.repository import RentalRepository
from rental_alert_bot.schema import LATEST_SCHEMA_VERSION
from rental_alert_bot.schema_check import read_schema_version

NOW = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)


def repository(path: Path) -> tuple[Database, RentalRepository]:
    database = Database(path)
    database.initialize()
    return database, RentalRepository(database, clock=lambda: NOW)


def create_active_subscription(repo: RentalRepository):
    subscription = repo.create_subscription(
        name="台北測試",
        source_url="https://rent.591.com.tw/list?region=1",
        normalized_url="https://rent.591.com.tw/list?region=1&sort=posttime",
    )
    return repo.activate_subscription(subscription.id)


def test_phase5_readiness_passes_with_due_active_subscription(
    tmp_path: Path,
) -> None:
    database, repo = repository(tmp_path / "rental.db")
    create_active_subscription(repo)

    result = check_phase5_readiness(
        database,
        now=NOW,
        poll_interval_seconds=300,
        poll_jitter_seconds=20,
        requirements=Phase5Requirements(
            minimum_runtime_hours=8,
            minimum_monitor_runs=90,
            minimum_image_spot_checks=0,
        ),
    )

    assert result.ready is True
    assert result.active_subscriptions == 1
    assert result.due_subscriptions == 1
    assert result.guaranteed_runtime_hours_for_minimum_runs <= 8
    assert result.lines()[0] == "PHASE5_READINESS_OK"


def test_phase5_readiness_warns_when_default_jitter_needs_longer_runtime(
    tmp_path: Path,
) -> None:
    database, repo = repository(tmp_path / "rental.db")
    create_active_subscription(repo)

    result = check_phase5_readiness(
        database,
        now=NOW,
        poll_interval_seconds=300,
        poll_jitter_seconds=30,
        requirements=Phase5Requirements(
            minimum_runtime_hours=8,
            minimum_monitor_runs=90,
            minimum_image_spot_checks=0,
        ),
    )

    assert result.ready is True
    assert result.guaranteed_runtime_hours_for_minimum_runs > 8
    assert any("worst-case poll interval" in warning for warning in result.warnings)


def test_phase5_readiness_fails_without_active_subscription(tmp_path: Path) -> None:
    database = Database(tmp_path / "rental.db")
    database.initialize()

    result = check_phase5_readiness(
        database,
        now=NOW,
        poll_interval_seconds=300,
        poll_jitter_seconds=20,
    )

    assert result.ready is False
    assert any("no active subscriptions" in failure for failure in result.failures)


def test_phase5_readiness_fails_when_active_subscription_is_not_due(
    tmp_path: Path,
) -> None:
    database, repo = repository(tmp_path / "rental.db")
    subscription = create_active_subscription(repo)
    repo.record_check(
        subscription.id,
        result_count=1,
        succeeded=True,
        next_check_at=NOW + timedelta(minutes=5),
    )

    result = check_phase5_readiness(
        database,
        now=NOW,
        poll_interval_seconds=300,
        poll_jitter_seconds=20,
    )

    assert result.ready is False
    assert result.active_subscriptions == 1
    assert result.due_subscriptions == 0
    assert any("no active subscriptions are due" in failure for failure in result.failures)


def test_phase5_readiness_rejects_invalid_poll_settings(tmp_path: Path) -> None:
    database = Database(tmp_path / "rental.db")
    database.initialize()

    with pytest.raises(ValueError, match="poll_interval_seconds"):
        check_phase5_readiness(
            database,
            now=NOW,
            poll_interval_seconds=0,
            poll_jitter_seconds=20,
        )


def test_read_schema_version_does_not_create_missing_database(tmp_path: Path) -> None:
    path = tmp_path / "missing.db"

    assert read_schema_version(path) is None
    assert path.exists() is False


def test_read_schema_version_uses_read_only_database_access(tmp_path: Path) -> None:
    database = Database(tmp_path / "rental.db")
    database.initialize()

    assert read_schema_version(database.path) == LATEST_SCHEMA_VERSION
