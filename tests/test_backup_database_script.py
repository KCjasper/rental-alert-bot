import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_backup_script_does_not_migrate_source_database(tmp_path: Path) -> None:
    source = tmp_path / "old.db"
    destination = tmp_path / "backup.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE marker (id INTEGER PRIMARY KEY)")
        connection.execute("PRAGMA user_version = 2")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/backup_database.py",
            "--source",
            str(source),
            "--destination",
            str(destination),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": "src"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "BACKUP_OK" in result.stdout
    with sqlite3.connect(source) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
    with sqlite3.connect(destination) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2


def test_backup_script_rejects_missing_source_database(tmp_path: Path) -> None:
    source = tmp_path / "missing.db"
    destination = tmp_path / "backup.db"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/backup_database.py",
            "--source",
            str(source),
            "--destination",
            str(destination),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": "src"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "source database does not exist" in result.stderr
    assert source.exists() is False
    assert destination.exists() is False
