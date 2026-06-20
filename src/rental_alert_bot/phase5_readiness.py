"""Phase 5 long-running validation readiness checks."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rental_alert_bot.database import Database, DatabaseError
from rental_alert_bot.phase5_validation import Phase5Requirements


@dataclass(frozen=True, slots=True)
class Phase5ReadinessResult:
    database_path: Path
    database_integrity_ok: bool
    active_subscriptions: int
    due_subscriptions: int
    poll_interval_seconds: int
    poll_jitter_seconds: int
    worst_case_check_period_seconds: int
    guaranteed_runtime_hours_for_minimum_runs: float
    requirements: Phase5Requirements
    failures: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.failures

    def lines(self) -> tuple[str, ...]:
        status = "PHASE5_READINESS_OK" if self.ready else "PHASE5_READINESS_NOT_READY"
        base_lines = (
            status,
            f"database={self.database_path}",
            f"database_integrity_ok={self.database_integrity_ok}",
            f"active_subscriptions={self.active_subscriptions}",
            f"due_subscriptions={self.due_subscriptions}",
            f"poll_interval_seconds={self.poll_interval_seconds}",
            f"poll_jitter_seconds={self.poll_jitter_seconds}",
            f"worst_case_check_period_seconds={self.worst_case_check_period_seconds}",
            "guaranteed_runtime_hours_for_minimum_runs="
            f"{self.guaranteed_runtime_hours_for_minimum_runs:.2f}",
            f"minimum_monitor_runs={self.requirements.minimum_monitor_runs}",
            f"minimum_runtime_hours={self.requirements.minimum_runtime_hours:.2f}",
        )
        issue_lines = tuple(f"failure={failure}" for failure in self.failures)
        warning_lines = tuple(f"warning={warning}" for warning in self.warnings)
        return base_lines + issue_lines + warning_lines


def check_phase5_readiness(
    database: Database,
    *,
    now: datetime,
    poll_interval_seconds: int,
    poll_jitter_seconds: int,
    requirements: Phase5Requirements | None = None,
) -> Phase5ReadinessResult:
    requirements = requirements or Phase5Requirements()
    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be greater than zero")
    if poll_jitter_seconds < 0:
        raise ValueError("poll_jitter_seconds must be zero or greater")

    try:
        database.check_integrity()
        database_integrity_ok = True
    except DatabaseError:
        database_integrity_ok = False

    now_text = now.isoformat(timespec="microseconds")
    with database.connect() as connection:
        connection.row_factory = sqlite3.Row
        active_subscriptions = _count(
            connection,
            "SELECT COUNT(*) FROM subscriptions WHERE status = 'active'",
        )
        due_subscriptions = _count(
            connection,
            """
            SELECT COUNT(*)
            FROM subscriptions
            WHERE status = 'active'
                AND (next_check_at IS NULL OR next_check_at <= ?)
            """,
            (now_text,),
        )

    worst_case_period = poll_interval_seconds + poll_jitter_seconds
    guaranteed_runtime_hours = _guaranteed_runtime_hours(
        minimum_runs=requirements.minimum_monitor_runs,
        worst_case_period_seconds=worst_case_period,
    )

    failures: list[str] = []
    warnings: list[str] = []
    if not database_integrity_ok:
        failures.append("SQLite integrity check failed")
    if active_subscriptions == 0:
        failures.append("no active subscriptions are available for phase 5 validation")
    if due_subscriptions == 0:
        failures.append("no active subscriptions are due at validation start")
    if guaranteed_runtime_hours > requirements.minimum_runtime_hours:
        warnings.append(
            "worst-case poll interval needs "
            f"{guaranteed_runtime_hours:.2f} hours for "
            f"{requirements.minimum_monitor_runs} checked runs"
        )

    return Phase5ReadinessResult(
        database_path=database.path,
        database_integrity_ok=database_integrity_ok,
        active_subscriptions=active_subscriptions,
        due_subscriptions=due_subscriptions,
        poll_interval_seconds=poll_interval_seconds,
        poll_jitter_seconds=poll_jitter_seconds,
        worst_case_check_period_seconds=worst_case_period,
        guaranteed_runtime_hours_for_minimum_runs=guaranteed_runtime_hours,
        requirements=requirements,
        failures=tuple(failures),
        warnings=tuple(warnings),
    )


def _guaranteed_runtime_hours(
    *,
    minimum_runs: int,
    worst_case_period_seconds: int,
) -> float:
    if minimum_runs <= 0:
        return 0.0
    return ((minimum_runs - 1) * worst_case_period_seconds) / 3600


def read_schema_version(path: Path) -> int | None:
    if not path.exists():
        return None
    uri = path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])


def _count(
    connection: sqlite3.Connection,
    query: str,
    parameters: tuple[object, ...] = (),
) -> int:
    return int(connection.execute(query, parameters).fetchone()[0])
