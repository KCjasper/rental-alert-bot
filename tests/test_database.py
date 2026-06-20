import sqlite3
from pathlib import Path

import pytest

from rental_alert_bot.database import Database, DatabaseError
from rental_alert_bot.schema import LATEST_SCHEMA_VERSION


def test_initializes_schema_with_integrity_settings(tmp_path: Path) -> None:
    database = Database(tmp_path / "state" / "rental.db")

    database.initialize()

    with database.connect() as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        listing_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(listings)").fetchall()
        }

    assert version == LATEST_SCHEMA_VERSION
    assert foreign_keys == 1
    assert journal_mode == "wal"
    assert {
        "subscriptions",
        "listings",
        "subscription_listings",
        "notification_events",
        "pending_actions",
        "monitor_runs",
    } <= tables
    assert "image_url" in listing_columns


def test_initialize_is_idempotent(tmp_path: Path) -> None:
    database = Database(tmp_path / "rental.db")

    database.initialize()
    database.initialize()

    database.check_integrity()


def test_rejects_database_from_newer_schema(tmp_path: Path) -> None:
    path = tmp_path / "future.db"
    connection = sqlite3.connect(path)
    connection.execute(f"PRAGMA user_version = {LATEST_SCHEMA_VERSION + 1}")
    connection.close()

    with pytest.raises(DatabaseError, match="newer than supported"):
        Database(path).initialize()


def test_creates_verified_backup_without_overwriting(tmp_path: Path) -> None:
    source = Database(tmp_path / "rental.db")
    source.initialize()
    destination = tmp_path / "backups" / "rental-backup.db"

    backup_path = source.backup_to(destination)

    assert backup_path == destination
    Database(destination).check_integrity()
    with pytest.raises(FileExistsError, match="already exists"):
        source.backup_to(destination)
