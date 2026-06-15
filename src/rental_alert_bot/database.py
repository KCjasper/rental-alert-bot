"""SQLite connection, migration, integrity, and backup helpers."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from rental_alert_bot.schema import LATEST_SCHEMA_VERSION, MIGRATIONS


class DatabaseError(RuntimeError):
    """Raised when the application database cannot be safely used."""


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        with self.connect() as connection:
            current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])

        if current_version > LATEST_SCHEMA_VERSION:
            raise DatabaseError(
                f"database schema {current_version} is newer than supported "
                f"version {LATEST_SCHEMA_VERSION}"
            )

        for version, migration in enumerate(
            MIGRATIONS[current_version:],
            start=current_version + 1,
        ):
            self._apply_migration(version, migration)

        self.check_integrity()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.path,
            timeout=5,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def check_integrity(self) -> None:
        with self.connect() as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()

        if result != "ok" or foreign_key_errors:
            raise DatabaseError("database integrity check failed")

    def backup_to(self, destination: Path | str) -> Path:
        destination_path = Path(destination)
        if destination_path.exists():
            raise FileExistsError(f"backup already exists: {destination_path}")

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as source:
            target = sqlite3.connect(destination_path)
            try:
                source.backup(target)
            finally:
                target.close()

        Database(destination_path).check_integrity()
        return destination_path

    def _apply_migration(self, version: int, migration: str) -> None:
        script = (
            "BEGIN IMMEDIATE;\n"
            f"{migration}\n"
            f"PRAGMA user_version = {version};\n"
            "COMMIT;"
        )
        with self.connect() as connection:
            try:
                connection.executescript(script)
            except sqlite3.Error as exc:
                with suppress(sqlite3.Error):
                    connection.rollback()
                raise DatabaseError(f"database migration {version} failed") from exc
