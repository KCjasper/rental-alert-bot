"""Create a verified online backup of the SQLite database."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from rental_alert_bot.database import Database


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(os.environ.get("DATABASE_PATH", "./data/rental_alert.db")),
    )
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()

    source = Database(args.source)
    source.initialize()
    backup_path = source.backup_to(args.destination)
    print(f"BACKUP_OK source={source.path} destination={backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
