"""Check whether local state is ready for phase 5 long-running validation."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from rental_alert_bot.config import Settings
from rental_alert_bot.database import Database
from rental_alert_bot.phase5_readiness import check_phase5_readiness
from rental_alert_bot.phase5_validation import Phase5Requirements


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
    database = Database(args.database or settings.database_path)
    database.initialize()

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
