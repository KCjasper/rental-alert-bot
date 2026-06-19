"""Print a read-only local monitoring status report."""

from __future__ import annotations

from datetime import UTC, datetime

from rental_alert_bot.config import Settings
from rental_alert_bot.database import Database
from rental_alert_bot.status_report import build_monitor_status


def main() -> int:
    settings = Settings.from_environment(require_secrets=False)
    database = Database(settings.database_path)
    database.initialize()
    status = build_monitor_status(database, now=datetime.now(UTC))
    for line in status.lines():
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
