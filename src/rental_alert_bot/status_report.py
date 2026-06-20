"""Read-only operational status reporting for local validation."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rental_alert_bot.database import Database


@dataclass(frozen=True, slots=True)
class MonitorStatus:
    database_path: Path
    active_subscriptions: int
    paused_subscriptions: int
    due_subscriptions: int
    pending_notifications: int
    sent_notifications: int
    failed_notifications: int
    latest_check_at: str | None
    monitor_run_count: int
    checked_monitor_run_count: int
    failed_monitor_run_count: int
    latest_monitor_run_at: str | None
    service_start_count: int
    running_service_run_count: int
    stopped_service_run_count: int
    failed_service_run_count: int
    latest_service_start_at: str | None
    latest_service_stop_at: str | None

    def lines(self) -> tuple[str, ...]:
        return (
            f"database={self.database_path}",
            f"active_subscriptions={self.active_subscriptions}",
            f"paused_subscriptions={self.paused_subscriptions}",
            f"due_subscriptions={self.due_subscriptions}",
            f"pending_notifications={self.pending_notifications}",
            f"sent_notifications={self.sent_notifications}",
            f"failed_notifications={self.failed_notifications}",
            f"latest_check_at={self.latest_check_at or 'none'}",
            f"monitor_run_count={self.monitor_run_count}",
            f"checked_monitor_run_count={self.checked_monitor_run_count}",
            f"failed_monitor_run_count={self.failed_monitor_run_count}",
            f"latest_monitor_run_at={self.latest_monitor_run_at or 'none'}",
            f"service_start_count={self.service_start_count}",
            f"running_service_run_count={self.running_service_run_count}",
            f"stopped_service_run_count={self.stopped_service_run_count}",
            f"failed_service_run_count={self.failed_service_run_count}",
            f"latest_service_start_at={self.latest_service_start_at or 'none'}",
            f"latest_service_stop_at={self.latest_service_stop_at or 'none'}",
        )


def build_monitor_status(database: Database, *, now: datetime) -> MonitorStatus:
    with database.connect() as connection:
        connection.row_factory = sqlite3.Row
        active_count = _count(
            connection,
            "SELECT COUNT(*) FROM subscriptions WHERE status = 'active'",
        )
        paused_count = _count(
            connection,
            "SELECT COUNT(*) FROM subscriptions WHERE status = 'paused'",
        )
        due_count = _count(
            connection,
            """
            SELECT COUNT(*)
            FROM subscriptions
            WHERE status = 'active'
                AND (next_check_at IS NULL OR next_check_at <= ?)
            """,
            (now.isoformat(timespec="microseconds"),),
        )
        pending_count = _count(
            connection,
            """
            SELECT COUNT(*)
            FROM subscription_listings AS sl
            JOIN subscriptions AS s ON s.id = sl.subscription_id
            WHERE sl.notified_at IS NULL
                AND s.status IN ('pending', 'active')
            """,
        )
        sent_count = _count(
            connection,
            "SELECT COUNT(*) FROM notification_events WHERE status = 'sent'",
        )
        failed_count = _count(
            connection,
            "SELECT COUNT(*) FROM notification_events WHERE status = 'failed'",
        )
        latest_check = connection.execute(
            "SELECT MAX(last_checked_at) FROM subscriptions",
        ).fetchone()[0]
        monitor_run_count = _count(connection, "SELECT COUNT(*) FROM monitor_runs")
        checked_monitor_run_count = _count(
            connection,
            "SELECT COUNT(*) FROM monitor_runs WHERE checked_count > 0",
        )
        failed_monitor_run_count = _count(
            connection,
            "SELECT COUNT(*) FROM monitor_runs WHERE status != 'completed'",
        )
        latest_monitor_run_at = connection.execute(
            "SELECT MAX(completed_at) FROM monitor_runs",
        ).fetchone()[0]
        service_start_count = _count(connection, "SELECT COUNT(*) FROM service_runs")
        running_service_run_count = _count(
            connection,
            "SELECT COUNT(*) FROM service_runs WHERE status = 'running'",
        )
        stopped_service_run_count = _count(
            connection,
            "SELECT COUNT(*) FROM service_runs WHERE status = 'stopped'",
        )
        failed_service_run_count = _count(
            connection,
            "SELECT COUNT(*) FROM service_runs WHERE status = 'failed'",
        )
        latest_service_start_at = connection.execute(
            "SELECT MAX(started_at) FROM service_runs",
        ).fetchone()[0]
        latest_service_stop_at = connection.execute(
            "SELECT MAX(stopped_at) FROM service_runs",
        ).fetchone()[0]

    return MonitorStatus(
        database_path=database.path,
        active_subscriptions=active_count,
        paused_subscriptions=paused_count,
        due_subscriptions=due_count,
        pending_notifications=pending_count,
        sent_notifications=sent_count,
        failed_notifications=failed_count,
        latest_check_at=latest_check,
        monitor_run_count=monitor_run_count,
        checked_monitor_run_count=checked_monitor_run_count,
        failed_monitor_run_count=failed_monitor_run_count,
        latest_monitor_run_at=latest_monitor_run_at,
        service_start_count=service_start_count,
        running_service_run_count=running_service_run_count,
        stopped_service_run_count=stopped_service_run_count,
        failed_service_run_count=failed_service_run_count,
        latest_service_start_at=latest_service_start_at,
        latest_service_stop_at=latest_service_stop_at,
    )


def _count(
    connection: sqlite3.Connection,
    query: str,
    parameters: tuple[object, ...] = (),
) -> int:
    return int(connection.execute(query, parameters).fetchone()[0])
