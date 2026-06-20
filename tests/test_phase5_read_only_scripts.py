import os
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
