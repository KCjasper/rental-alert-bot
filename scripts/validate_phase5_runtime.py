"""Validate phase 5 long-running local monitor evidence."""

from __future__ import annotations

import argparse
from pathlib import Path

from rental_alert_bot.config import Settings
from rental_alert_bot.database import Database
from rental_alert_bot.phase5_image_audit import summarize_image_audit_file
from rental_alert_bot.phase5_validation import (
    Phase5Requirements,
    validate_phase5_runtime,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate phase 5 runtime evidence from the SQLite database.",
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
        help="Minimum accepted monitor run count. Default: 90.",
    )
    parser.add_argument(
        "--manual-image-spot-checks",
        type=int,
        default=0,
        help="Number of manually verified Telegram image notifications.",
    )
    parser.add_argument(
        "--image-audit-file",
        type=Path,
        help=(
            "Completed CSV from export_phase5_image_audit.py. "
            "When provided, passed rows override --manual-image-spot-checks."
        ),
    )
    parser.add_argument(
        "--minimum-image-spot-checks",
        type=int,
        default=20,
        help="Minimum accepted manual image spot checks. Default: 20.",
    )
    args = parser.parse_args()

    settings = Settings.from_environment(require_secrets=False)
    database = Database(args.database or settings.database_path)
    database.initialize()
    manual_image_spot_checks = args.manual_image_spot_checks
    failed_image_spot_checks = 0
    incomplete_image_spot_checks = 0
    if args.image_audit_file is not None:
        audit_summary = summarize_image_audit_file(args.image_audit_file)
        manual_image_spot_checks = audit_summary.passed_checks
        failed_image_spot_checks = audit_summary.failed_checks
        incomplete_image_spot_checks = audit_summary.incomplete_checks

    result = validate_phase5_runtime(
        database,
        requirements=Phase5Requirements(
            minimum_runtime_hours=args.minimum_runtime_hours,
            minimum_monitor_runs=args.minimum_monitor_runs,
            minimum_image_spot_checks=args.minimum_image_spot_checks,
        ),
        manual_image_spot_checks=manual_image_spot_checks,
        failed_image_spot_checks=failed_image_spot_checks,
        incomplete_image_spot_checks=incomplete_image_spot_checks,
    )
    for line in result.lines():
        print(line)
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
