"""Initialize or migrate the configured SQLite database."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from rental_alert_bot.database import Database
from rental_alert_bot.schema import LATEST_SCHEMA_VERSION


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--path",
        type=Path,
        default=Path(os.environ.get("DATABASE_PATH", "./data/rental_alert.db")),
    )
    args = parser.parse_args()

    database = Database(args.path)
    database.initialize()
    print(f"DATABASE_READY path={database.path} schema={LATEST_SCHEMA_VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
