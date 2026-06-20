"""Phase 5 long-running monitor validation helpers."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rental_alert_bot.database import Database, DatabaseError


@dataclass(frozen=True, slots=True)
class Phase5Requirements:
    minimum_runtime_hours: float = 8.0
    minimum_monitor_runs: int = 90
    minimum_image_spot_checks: int = 20


@dataclass(frozen=True, slots=True)
class Phase5ValidationResult:
    database_path: Path
    database_integrity_ok: bool
    evidence_since: str | None
    evidence_until: str | None
    monitor_run_count: int
    checked_monitor_run_count: int
    failed_monitor_run_count: int
    first_started_at: str | None
    latest_completed_at: str | None
    runtime_hours: float
    duplicate_sent_notification_count: int
    image_listing_count: int
    photo_fallback_failure_count: int
    manual_image_spot_checks: int
    failed_image_spot_checks: int
    incomplete_image_spot_checks: int
    requirements: Phase5Requirements
    failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.failures

    def lines(self) -> tuple[str, ...]:
        status = (
            "PHASE5_RUNTIME_VALIDATION_OK"
            if self.passed
            else "PHASE5_RUNTIME_VALIDATION_INCOMPLETE"
        )
        base_lines = (
            status,
            f"database={self.database_path}",
            f"database_integrity_ok={self.database_integrity_ok}",
            f"evidence_since={self.evidence_since or 'none'}",
            f"evidence_until={self.evidence_until or 'none'}",
            f"monitor_run_count={self.monitor_run_count}",
            f"checked_monitor_run_count={self.checked_monitor_run_count}",
            f"minimum_monitor_runs={self.requirements.minimum_monitor_runs}",
            f"failed_monitor_run_count={self.failed_monitor_run_count}",
            f"first_started_at={self.first_started_at or 'none'}",
            f"latest_completed_at={self.latest_completed_at or 'none'}",
            f"runtime_hours={self.runtime_hours:.2f}",
            f"minimum_runtime_hours={self.requirements.minimum_runtime_hours:.2f}",
            f"duplicate_sent_notification_count={self.duplicate_sent_notification_count}",
            f"image_listing_count={self.image_listing_count}",
            f"photo_fallback_failure_count={self.photo_fallback_failure_count}",
            f"manual_image_spot_checks={self.manual_image_spot_checks}",
            f"failed_image_spot_checks={self.failed_image_spot_checks}",
            f"incomplete_image_spot_checks={self.incomplete_image_spot_checks}",
            f"minimum_image_spot_checks={self.requirements.minimum_image_spot_checks}",
        )
        if not self.failures:
            return base_lines
        return base_lines + tuple(f"failure={failure}" for failure in self.failures)


def validate_phase5_runtime(
    database: Database,
    *,
    requirements: Phase5Requirements | None = None,
    manual_image_spot_checks: int = 0,
    failed_image_spot_checks: int = 0,
    incomplete_image_spot_checks: int = 0,
    evidence_since: datetime | None = None,
    evidence_until: datetime | None = None,
) -> Phase5ValidationResult:
    requirements = requirements or Phase5Requirements()
    if (
        evidence_since is not None
        and evidence_until is not None
        and evidence_since > evidence_until
    ):
        raise ValueError("evidence_since must be earlier than evidence_until")
    try:
        database.check_integrity()
        database_integrity_ok = True
    except DatabaseError:
        database_integrity_ok = False

    with database.connect() as connection:
        connection.row_factory = sqlite3.Row
        run_filter, run_parameters = _monitor_run_filter(
            evidence_since=evidence_since,
            evidence_until=evidence_until,
        )
        run_summary = connection.execute(
            f"""
            SELECT
                COUNT(*) AS monitor_run_count,
                SUM(CASE WHEN checked_count > 0 THEN 1 ELSE 0 END)
                    AS checked_monitor_run_count,
                SUM(CASE WHEN status != 'completed' THEN 1 ELSE 0 END)
                    AS failed_monitor_run_count,
                MIN(started_at) AS first_started_at,
                MAX(completed_at) AS latest_completed_at
            FROM monitor_runs
            {run_filter}
            """,
            run_parameters,
        ).fetchone()
        duplicate_sent_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT subscription_id, listing_id
                    FROM notification_events
                    WHERE status = 'sent'
                    GROUP BY subscription_id, listing_id
                    HAVING COUNT(*) > 1
                )
                """
            ).fetchone()[0]
        )
        image_listing_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM listings
                WHERE image_url IS NOT NULL AND TRIM(image_url) != ''
                """
            ).fetchone()[0]
        )
        photo_fallback_failure_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM notification_events
                WHERE status = 'failed' AND error_code LIKE 'telegram_photo_%'
                """
            ).fetchone()[0]
        )

    first_started_at = run_summary["first_started_at"]
    latest_completed_at = run_summary["latest_completed_at"]
    runtime_hours = _runtime_hours(first_started_at, latest_completed_at)
    monitor_run_count = int(run_summary["monitor_run_count"] or 0)
    checked_monitor_run_count = int(run_summary["checked_monitor_run_count"] or 0)
    failed_monitor_run_count = int(run_summary["failed_monitor_run_count"] or 0)

    failures: list[str] = []
    if not database_integrity_ok:
        failures.append("SQLite integrity check failed")
    if checked_monitor_run_count < requirements.minimum_monitor_runs:
        failures.append(
            "checked monitor runs "
            f"{checked_monitor_run_count} < {requirements.minimum_monitor_runs}"
        )
    if runtime_hours < requirements.minimum_runtime_hours:
        failures.append(
            f"runtime hours {runtime_hours:.2f} < {requirements.minimum_runtime_hours:.2f}"
        )
    if failed_monitor_run_count:
        failures.append(f"unhandled monitor failures recorded: {failed_monitor_run_count}")
    if duplicate_sent_count:
        failures.append(f"duplicate sent notification relations: {duplicate_sent_count}")
    if manual_image_spot_checks < requirements.minimum_image_spot_checks:
        failures.append(
            "manual image spot checks "
            f"{manual_image_spot_checks} < {requirements.minimum_image_spot_checks}"
        )
    if failed_image_spot_checks:
        failures.append(f"failed image spot checks: {failed_image_spot_checks}")
    if image_listing_count < manual_image_spot_checks:
        failures.append(
            f"image listings {image_listing_count} < manual image spot checks "
            f"{manual_image_spot_checks}"
        )

    return Phase5ValidationResult(
        database_path=database.path,
        database_integrity_ok=database_integrity_ok,
        evidence_since=_isoformat(evidence_since),
        evidence_until=_isoformat(evidence_until),
        monitor_run_count=monitor_run_count,
        checked_monitor_run_count=checked_monitor_run_count,
        failed_monitor_run_count=failed_monitor_run_count,
        first_started_at=first_started_at,
        latest_completed_at=latest_completed_at,
        runtime_hours=runtime_hours,
        duplicate_sent_notification_count=duplicate_sent_count,
        image_listing_count=image_listing_count,
        photo_fallback_failure_count=photo_fallback_failure_count,
        manual_image_spot_checks=manual_image_spot_checks,
        failed_image_spot_checks=failed_image_spot_checks,
        incomplete_image_spot_checks=incomplete_image_spot_checks,
        requirements=requirements,
        failures=tuple(failures),
    )


def _monitor_run_filter(
    *,
    evidence_since: datetime | None,
    evidence_until: datetime | None,
) -> tuple[str, tuple[str, ...]]:
    clauses: list[str] = []
    parameters: list[str] = []
    if evidence_since is not None:
        clauses.append("started_at >= ?")
        parameters.append(evidence_since.isoformat(timespec="microseconds"))
    if evidence_until is not None:
        clauses.append("completed_at <= ?")
        parameters.append(evidence_until.isoformat(timespec="microseconds"))
    if not clauses:
        return "", ()
    return "WHERE " + " AND ".join(clauses), tuple(parameters)


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat(timespec="microseconds") if value is not None else None


def _runtime_hours(first_started_at: str | None, latest_completed_at: str | None) -> float:
    if first_started_at is None or latest_completed_at is None:
        return 0.0

    started = datetime.fromisoformat(first_started_at)
    completed = datetime.fromisoformat(latest_completed_at)
    seconds = max((completed - started).total_seconds(), 0.0)
    return seconds / 3600
