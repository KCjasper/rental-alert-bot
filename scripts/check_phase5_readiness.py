"""Check whether local state is ready for phase 5 long-running validation."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from rental_alert_bot.config import Settings
from rental_alert_bot.database import Database
from rental_alert_bot.phase5_readiness import check_phase5_readiness, read_schema_version
from rental_alert_bot.phase5_validation import Phase5Requirements
from rental_alert_bot.schema import LATEST_SCHEMA_VERSION


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check phase 5 long-running validation readiness.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        help="SQLite database path. Defaults to DATABASE_PATH or ./data/rental_alert.db.",
    )
    parser.add_argument(
        "--minimum-runtime-hours",
        type=float,
        default=8.0,
        help="Minimum accepted runtime window. Default: 8.0.",
    )
    parser.add_argument(
        "--minimum-monitor-runs",
        type=int,
        default=90,
        help="Minimum accepted checked monitor run count. Default: 90.",
    )
    args = parser.parse_args()

    settings = Settings.from_environment(require_secrets=False)
    database_path = args.database or settings.database_path
    schema_version = read_schema_version(database_path)
    if schema_version is None:
        print("PHASE5_READINESS_NOT_READY")
        print(f"database={database_path}")
        print(f"failure=database file does not exist: {database_path}")
        return 1
    if schema_version != LATEST_SCHEMA_VERSION:
        print("PHASE5_READINESS_NOT_READY")
        print(f"database={database_path}")
        print(f"schema_version={schema_version}")
        print(f"required_schema_version={LATEST_SCHEMA_VERSION}")
        print("failure=database schema is not current; create a backup, then run init_database")
        return 1

    database = Database(database_path)
    result = check_phase5_readiness(
        database,
        now=datetime.now(UTC),
        poll_interval_seconds=settings.poll_interval_seconds,
        poll_jitter_seconds=settings.poll_jitter_seconds,
        requirements=Phase5Requirements(
            minimum_runtime_hours=args.minimum_runtime_hours,
            minimum_monitor_runs=args.minimum_monitor_runs,
            minimum_image_spot_checks=0,
        ),
    )
    for line in result.lines():
        print(line)
    return 0 if result.ready else 1

if __name__ == "__main__":
    raise SystemExit(main())
