"""Report evidence for the phase 4 private Telegram Bot validation gate."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from rental_alert_bot.database import Database

REQUIRED_COMMANDS = (
    "/start",
    "url",
    "confirm",
    "/cancel",
    "/subscriptions",
    "/pause",
    "/resume",
    "/test",
    "/delete",
)


def main() -> int:
    database_path = Path(os.environ.get("DATABASE_PATH", "./data/rental_alert.db"))
    database = Database(database_path)
    database.initialize()

    with database.connect() as connection:
        connection.row_factory = sqlite3.Row
        command_counts = {
            row["command"]: int(row["count"])
            for row in connection.execute(
                """
                SELECT command, COUNT(*) AS count
                FROM bot_command_events
                WHERE authorized = 1 AND status = 'accepted'
                GROUP BY command
                """
            ).fetchall()
        }
        rejected_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM bot_command_events WHERE authorized = 0"
            ).fetchone()[0]
        )
        active_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM subscriptions WHERE status = 'active'"
            ).fetchone()[0]
        )
        deleted_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM subscriptions WHERE status = 'deleted'"
            ).fetchone()[0]
        )
        subscription_count = int(
            connection.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0]
        )
        sent_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM notification_events WHERE status = 'sent'"
            ).fetchone()[0]
        )
        consumed_subscription_id_prompts = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM pending_actions
                WHERE action_type = 'await_subscription_id'
                    AND status = 'consumed'
                """
            ).fetchone()[0]
        )

    print(f"database={database_path}")
    print(f"active_subscriptions={active_count}")
    print(f"deleted_subscriptions={deleted_count}")
    print(f"total_subscriptions={subscription_count}")
    print(f"sent_notifications={sent_count}")
    print(f"unauthorized_rejections={rejected_count}")
    print(f"consumed_subscription_id_prompts={consumed_subscription_id_prompts}")
    print("commands:")

    missing: list[str] = []
    for command in REQUIRED_COMMANDS:
        count = command_counts.get(command, 0)
        marker = "OK" if count else "MISSING"
        print(f"  {marker} {command}: {count}")
        if not count:
            missing.append(command)

    if subscription_count < 1:
        missing.append("subscription")
    if sent_count < 1:
        missing.append("sent notification")
    if consumed_subscription_id_prompts < 1:
        missing.append("interactive subscription id prompt")

    if missing:
        print("PHASE4_MANUAL_VALIDATION_INCOMPLETE")
        print("missing=" + ", ".join(missing))
        return 1

    print("PHASE4_MANUAL_VALIDATION_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
