import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rental_alert_bot.database import Database
from rental_alert_bot.listing import RentalListing
from rental_alert_bot.repository import RentalRepository

NOW = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)


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


def seed_phase4_database(path: Path, *, include_interactive_prompt: bool) -> None:
    database = Database(path)
    database.initialize()
    repo = RentalRepository(database, clock=lambda: NOW)
    subscription = repo.create_subscription(
        name="台北測試",
        source_url="https://rent.591.com.tw/list?region=1",
        normalized_url="https://rent.591.com.tw/list?region=1&sort=posttime",
    )
    repo.activate_subscription(subscription.id)
    repo.record_discovered_listings(subscription.id, [listing("90000001")])
    repo.record_notification_success(subscription.id, "90000001")

    for command in (
        "/start",
        "url",
        "confirm",
        "/cancel",
        "/subscriptions",
        "/pause",
        "/resume",
        "/test",
        "/delete",
    ):
        repo.record_bot_command_event(command=command, authorized=True, status="accepted")

    if include_interactive_prompt:
        action = repo.create_pending_action(
            action_type="await_subscription_id",
            payload={"operation": "pause"},
            expires_at=NOW + timedelta(minutes=30),
        )
        assert repo.complete_pending_action(action.id) is True


def run_validator(database_path: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_PATH"] = str(database_path)
    return subprocess.run(
        [sys.executable, "scripts/validate_phase4_manual.py"],
        check=False,
        cwd=Path(__file__).parents[1],
        env=env,
        text=True,
        capture_output=True,
    )


def test_phase4_validator_requires_interactive_subscription_id_prompt(tmp_path: Path) -> None:
    database_path = tmp_path / "rental.db"
    seed_phase4_database(database_path, include_interactive_prompt=False)

    result = run_validator(database_path)

    assert result.returncode == 1
    assert "interactive subscription id prompt" in result.stdout


def test_phase4_validator_accepts_interactive_subscription_id_prompt(tmp_path: Path) -> None:
    database_path = tmp_path / "rental.db"
    seed_phase4_database(database_path, include_interactive_prompt=True)

    result = run_validator(database_path)

    assert result.returncode == 0
    assert "PHASE4_MANUAL_VALIDATION_OK" in result.stdout
