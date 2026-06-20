"""Print a read-only local monitoring status report."""

from __future__ import annotations

from datetime import UTC, datetime

from rental_alert_bot.config import Settings
from rental_alert_bot.database import Database
from rental_alert_bot.schema_check import check_current_schema
from rental_alert_bot.status_report import build_monitor_status


def main() -> int:
    settings = Settings.from_environment(require_secrets=False)
    database = Database(settings.database_path)
    schema_check = check_current_schema(database.path)
    if not schema_check.current:
        for line in schema_check.not_ready_lines(status="MONITOR_STATUS_NOT_READY"):
            print(line)
        return 1

    status = build_monitor_status(database, now=datetime.now(UTC))
    for line in status.lines():
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
