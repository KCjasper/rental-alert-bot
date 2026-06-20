"""Phase 5 image notification audit export and parsing."""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from rental_alert_bot.database import Database

AUDIT_COLUMNS = (
    "subscription_id",
    "listing_id",
    "title",
    "listing_url",
    "image_url",
    "sent_at",
    "image_matches",
    "notes",
)

_POSITIVE_VALUES = {"1", "true", "yes", "y", "ok", "pass", "passed", "是", "對", "通過"}
_NEGATIVE_VALUES = {"0", "false", "no", "n", "fail", "failed", "否", "錯", "不通過"}


@dataclass(frozen=True, slots=True)
class ImageAuditCandidate:
    subscription_id: int
    listing_id: str
    title: str
    listing_url: str
    image_url: str
    sent_at: str


@dataclass(frozen=True, slots=True)
class ImageAuditSummary:
    total_rows: int
    passed_checks: int
    failed_checks: int
    incomplete_checks: int


def list_image_audit_candidates(
    database: Database,
    *,
    limit: int = 20,
) -> tuple[ImageAuditCandidate, ...]:
    if limit <= 0:
        raise ValueError("limit must be greater than zero")

    with database.connect() as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT
                ne.subscription_id,
                ne.listing_id,
                l.title,
                l.url AS listing_url,
                l.image_url,
                MAX(ne.sent_at) AS sent_at
            FROM notification_events AS ne
            JOIN listings AS l ON l.listing_id = ne.listing_id
            WHERE ne.status = 'sent'
                AND l.image_url IS NOT NULL
                AND TRIM(l.image_url) != ''
            GROUP BY ne.subscription_id, ne.listing_id
            ORDER BY sent_at DESC, ne.subscription_id, ne.listing_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return tuple(
        ImageAuditCandidate(
            subscription_id=int(row["subscription_id"]),
            listing_id=str(row["listing_id"]),
            title=str(row["title"]),
            listing_url=str(row["listing_url"]),
            image_url=str(row["image_url"]),
            sent_at=str(row["sent_at"]),
        )
        for row in rows
    )


def export_image_audit_template(
    database: Database,
    destination: Path | str,
    *,
    limit: int = 20,
) -> Path:
    destination_path = Path(destination)
    if destination_path.exists():
        raise FileExistsError(f"image audit file already exists: {destination_path}")

    candidates = list_image_audit_candidates(database, limit=limit)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    with destination_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=AUDIT_COLUMNS)
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(
                {
                    "subscription_id": candidate.subscription_id,
                    "listing_id": candidate.listing_id,
                    "title": candidate.title,
                    "listing_url": candidate.listing_url,
                    "image_url": candidate.image_url,
                    "sent_at": candidate.sent_at,
                    "image_matches": "",
                    "notes": "",
                }
            )
    return destination_path


def summarize_image_audit_file(path: Path | str) -> ImageAuditSummary:
    audit_path = Path(path)
    with audit_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        missing = set(AUDIT_COLUMNS) - set(reader.fieldnames or ())
        if missing:
            missing_columns = ", ".join(sorted(missing))
            raise ValueError(f"image audit file is missing columns: {missing_columns}")

        total_rows = 0
        passed_checks = 0
        failed_checks = 0
        incomplete_checks = 0
        for row in reader:
            total_rows += 1
            value = (row.get("image_matches") or "").strip().lower()
            if not value:
                incomplete_checks += 1
            elif value in _POSITIVE_VALUES:
                passed_checks += 1
            elif value in _NEGATIVE_VALUES:
                failed_checks += 1
            else:
                incomplete_checks += 1

    return ImageAuditSummary(
        total_rows=total_rows,
        passed_checks=passed_checks,
        failed_checks=failed_checks,
        incomplete_checks=incomplete_checks,
    )
