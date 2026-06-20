"""Read-only schema checks for scripts that must not migrate evidence databases."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from rental_alert_bot.schema import LATEST_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class SchemaCheckResult:
    database_path: Path
    schema_version: int | None
    required_schema_version: int = LATEST_SCHEMA_VERSION

    @property
    def current(self) -> bool:
        return self.schema_version == self.required_schema_version

    def not_ready_lines(self, *, status: str) -> tuple[str, ...]:
        schema_version = "missing" if self.schema_version is None else str(self.schema_version)
        return (
            status,
            f"database={self.database_path}",
            f"schema_version={schema_version}",
            f"required_schema_version={self.required_schema_version}",
            "failure=database schema is not current; create a backup, then run init_database",
        )


def check_current_schema(path: Path | str) -> SchemaCheckResult:
    database_path = Path(path)
    return SchemaCheckResult(
        database_path=database_path,
        schema_version=read_schema_version(database_path),
    )


def read_schema_version(path: Path) -> int | None:
    if not path.exists():
        return None
    uri = path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])
