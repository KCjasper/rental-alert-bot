"""Export a phase 5 image notification audit CSV template."""

from __future__ import annotations

import argparse
from pathlib import Path

from rental_alert_bot.config import Settings
from rental_alert_bot.database import Database
from rental_alert_bot.phase5_image_audit import export_image_audit_template
from rental_alert_bot.schema_check import check_current_schema


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export image notification candidates for phase 5 manual audit.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        help="SQLite database path. Defaults to DATABASE_PATH or ./data/rental_alert.db.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Destination CSV path. Existing files are never overwritten.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of image notification rows to export. Default: 20.",
    )
    args = parser.parse_args()

    settings = Settings.from_environment(require_secrets=False)
    database = Database(args.database or settings.database_path)
    schema_check = check_current_schema(database.path)
    if not schema_check.current:
        for line in schema_check.not_ready_lines(status="PHASE5_IMAGE_AUDIT_NOT_READY"):
            print(line)
        return 1

    destination = export_image_audit_template(database, args.output, limit=args.limit)
    print(f"PHASE5_IMAGE_AUDIT_EXPORTED path={destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
