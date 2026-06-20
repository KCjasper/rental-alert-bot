import json
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rental_alert_bot.database import Database
from rental_alert_bot.repository import RentalRepository

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 6, 21, 10, 0, tzinfo=UTC)


def test_validate_phase5_runtime_script_does_not_migrate_old_database(
    tmp_path: Path,
) -> None:
    database = create_old_database(tmp_path / "old.db")

    result = run_script(
        "scripts/validate_phase5_runtime.py",
        "--database",
        str(database),
    )

    assert result.returncode == 1
    assert "PHASE5_RUNTIME_VALIDATION_NOT_READY" in result.stdout
    assert "schema_version=4" in result.stdout
    assert "required_schema_version=5" in result.stdout
    assert schema_version(database) == 4


def test_export_phase5_image_audit_script_does_not_migrate_old_database(
    tmp_path: Path,
) -> None:
    database = create_old_database(tmp_path / "old.db")
    output = tmp_path / "audit.csv"

    result = run_script(
        "scripts/export_phase5_image_audit.py",
        "--database",
        str(database),
        "--output",
        str(output),
    )

    assert result.returncode == 1
    assert "PHASE5_IMAGE_AUDIT_NOT_READY" in result.stdout
    assert "schema_version=4" in result.stdout
    assert output.exists() is False
    assert schema_version(database) == 4


def test_monitor_status_script_does_not_migrate_old_database(tmp_path: Path) -> None:
    database = create_old_database(tmp_path / "old.db")

    result = run_script(
        "scripts/monitor_status.py",
        env={"DATABASE_PATH": str(database)},
    )

    assert result.returncode == 1
    assert "MONITOR_STATUS_NOT_READY" in result.stdout
    assert "schema_version=4" in result.stdout
    assert schema_version(database) == 4


def test_validate_phase5_runtime_script_accepts_window_file(tmp_path: Path) -> None:
    database_path = tmp_path / "rental.db"
    database = Database(database_path)
    database.initialize()
    repo = RentalRepository(database, clock=lambda: NOW)
    repo.record_monitor_run(
        started_at=NOW - timedelta(days=1),
        completed_at=NOW - timedelta(days=1) + timedelta(seconds=1),
        checked_count=1,
        succeeded_count=0,
        failed_count=1,
        sent_count=0,
        notification_failed_count=0,
        status="failed",
        error_code="old_failure",
    )
    repo.record_monitor_run(
        started_at=NOW,
        completed_at=NOW + timedelta(hours=8),
        checked_count=1,
        succeeded_count=1,
        failed_count=0,
        sent_count=0,
        notification_failed_count=0,
    )
    first_service = repo.record_service_start(
        process_name="local_service",
        started_at=NOW,
    )
    repo.record_service_stop(
        first_service.id,
        stopped_at=NOW + timedelta(seconds=1),
    )
    second_service = repo.record_service_start(
        process_name="local_service",
        started_at=NOW + timedelta(seconds=2),
    )
    repo.record_service_stop(
        second_service.id,
        stopped_at=NOW + timedelta(seconds=3),
    )
    window = tmp_path / "phase5-window.json"
    window.write_text(
        json.dumps(
            {
                "since": NOW.isoformat(timespec="microseconds"),
                "created_at": NOW.isoformat(timespec="microseconds"),
            },
        ),
        encoding="utf-8",
    )

    result = run_script(
        "scripts/validate_phase5_runtime.py",
        "--database",
        str(database_path),
        "--window-file",
        str(window),
        "--minimum-runtime-hours",
        "8",
        "--minimum-monitor-runs",
        "1",
        "--minimum-image-spot-checks",
        "0",
    )

    assert result.returncode == 0, result.stdout
    assert "PHASE5_RUNTIME_VALIDATION_OK" in result.stdout
    assert f"evidence_since={NOW.isoformat(timespec='microseconds')}" in result.stdout
    assert "failed_monitor_run_count=0" in result.stdout


def create_old_database(path: Path) -> Path:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE marker (id INTEGER PRIMARY KEY)")
        connection.execute("PRAGMA user_version = 4")
    return path


def schema_version(path: Path) -> int:
    with sqlite3.connect(path) as connection:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])


def run_script(
    script: str,
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, script, *args],
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONPATH": "src", **(env or {})},
        capture_output=True,
        text=True,
        check=False,
    )
