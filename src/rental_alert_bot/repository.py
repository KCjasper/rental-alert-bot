"""Transactional data access for subscriptions, listings, and notifications."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from rental_alert_bot.database import Database
from rental_alert_bot.listing import RentalListing


class RepositoryError(RuntimeError):
    """Base error for invalid repository operations."""


class DuplicateSubscriptionError(RepositoryError):
    """Raised when an equivalent normalized URL is already stored."""


class SubscriptionNotFoundError(RepositoryError):
    """Raised when a subscription does not exist."""


class InvalidSubscriptionStateError(RepositoryError):
    """Raised when a subscription transition is not allowed."""


class SubscriptionStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    PAUSED = "paused"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class Subscription:
    id: int
    name: str
    source_url: str
    normalized_url: str
    status: SubscriptionStatus
    created_at: datetime
    updated_at: datetime
    last_checked_at: datetime | None
    last_success_at: datetime | None
    next_check_at: datetime | None
    last_result_count: int | None
    deleted_at: datetime | None


@dataclass(frozen=True, slots=True)
class PendingNotification:
    subscription_id: int
    listing: RentalListing
    first_seen_at: datetime
    attempt_count: int


@dataclass(frozen=True, slots=True)
class PendingAction:
    id: int
    subscription_id: int | None
    action_type: str
    payload: dict[str, Any]
    status: str
    created_at: datetime
    expires_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class BotCommandEvent:
    id: int
    update_id: int | None
    command: str
    authorized: bool
    status: str
    subscription_id: int | None
    created_at: datetime
    error_code: str | None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


class RentalRepository:
    def __init__(
        self,
        database: Database,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._database = database
        self._clock = clock

    def create_subscription(
        self,
        *,
        name: str,
        source_url: str,
        normalized_url: str,
    ) -> Subscription:
        now = _timestamp(self._clock())
        try:
            with self._database.transaction() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO subscriptions (
                        name, source_url, normalized_url, status, created_at, updated_at
                    ) VALUES (?, ?, ?, 'pending', ?, ?)
                    """,
                    (name.strip(), source_url, normalized_url, now, now),
                )
                subscription_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            if "normalized_url" in str(exc):
                raise DuplicateSubscriptionError(
                    "an equivalent subscription already exists"
                ) from exc
            raise

        return self.get_subscription(subscription_id)

    def get_subscription(self, subscription_id: int) -> Subscription:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM subscriptions WHERE id = ?",
                (subscription_id,),
            ).fetchone()
        if row is None:
            raise SubscriptionNotFoundError(f"subscription {subscription_id} was not found")
        return self._subscription_from_row(row)

    def get_live_subscription(self, subscription_id: int) -> Subscription:
        with self._database.connect() as connection:
            row = self._require_subscription(
                connection,
                subscription_id,
                allow_deleted=False,
            )
        return self._subscription_from_row(row)

    def list_subscriptions(self, *, include_deleted: bool = False) -> tuple[Subscription, ...]:
        query = "SELECT * FROM subscriptions"
        parameters: tuple[object, ...] = ()
        if not include_deleted:
            query += " WHERE status != ?"
            parameters = (SubscriptionStatus.DELETED.value,)
        query += " ORDER BY id"

        with self._database.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(self._subscription_from_row(row) for row in rows)

    def list_due_subscriptions(self, due_at: datetime) -> tuple[Subscription, ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM subscriptions
                WHERE status = 'active'
                    AND (next_check_at IS NULL OR next_check_at <= ?)
                ORDER BY id
                """,
                (_timestamp(due_at),),
            ).fetchall()
        return tuple(self._subscription_from_row(row) for row in rows)

    def activate_subscription(self, subscription_id: int) -> Subscription:
        return self._transition_subscription(
            subscription_id,
            allowed={SubscriptionStatus.PENDING},
            target=SubscriptionStatus.ACTIVE,
        )

    def pause_subscription(self, subscription_id: int) -> Subscription:
        return self._transition_subscription(
            subscription_id,
            allowed={SubscriptionStatus.ACTIVE},
            target=SubscriptionStatus.PAUSED,
        )

    def resume_subscription(self, subscription_id: int) -> Subscription:
        return self._transition_subscription(
            subscription_id,
            allowed={SubscriptionStatus.PAUSED},
            target=SubscriptionStatus.ACTIVE,
        )

    def delete_subscription(self, subscription_id: int) -> Subscription:
        return self._transition_subscription(
            subscription_id,
            allowed={
                SubscriptionStatus.PENDING,
                SubscriptionStatus.ACTIVE,
                SubscriptionStatus.PAUSED,
            },
            target=SubscriptionStatus.DELETED,
        )

    def record_check(
        self,
        subscription_id: int,
        *,
        result_count: int,
        succeeded: bool,
        next_check_at: datetime | None = None,
    ) -> None:
        now = _timestamp(self._clock())
        with self._database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE subscriptions
                SET last_checked_at = ?,
                    last_success_at = CASE WHEN ? THEN ? ELSE last_success_at END,
                    last_result_count = CASE WHEN ? THEN ? ELSE last_result_count END,
                    next_check_at = ?,
                    updated_at = ?
                WHERE id = ? AND status != 'deleted'
                """,
                (
                    now,
                    succeeded,
                    now,
                    succeeded,
                    result_count,
                    _timestamp(next_check_at) if next_check_at else None,
                    now,
                    subscription_id,
                ),
            )
            if cursor.rowcount != 1:
                raise SubscriptionNotFoundError(
                    f"subscription {subscription_id} was not found"
                )

    def record_discovered_listings(
        self,
        subscription_id: int,
        listings: Iterable[RentalListing],
    ) -> tuple[str, ...]:
        now = _timestamp(self._clock())
        newly_discovered: list[str] = []

        with self._database.transaction() as connection:
            self._require_subscription(connection, subscription_id, allow_deleted=False)
            for listing in listings:
                connection.execute(
                    """
                    INSERT INTO listings (
                        listing_id, url, title, price_monthly, location, category,
                        layout, area_ping, floor, published_text, image_url,
                        first_seen_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(listing_id) DO UPDATE SET
                        url = excluded.url,
                        title = excluded.title,
                        price_monthly = excluded.price_monthly,
                        location = excluded.location,
                        category = excluded.category,
                        layout = excluded.layout,
                        area_ping = excluded.area_ping,
                        floor = excluded.floor,
                        published_text = excluded.published_text,
                        image_url = excluded.image_url,
                        last_seen_at = excluded.last_seen_at
                    """,
                    (
                        listing.listing_id,
                        listing.url,
                        listing.title,
                        listing.price_monthly,
                        listing.location,
                        listing.category,
                        listing.layout,
                        listing.area_ping,
                        listing.floor,
                        listing.published_text,
                        listing.image_url,
                        now,
                        now,
                    ),
                )
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO subscription_listings (
                        subscription_id, listing_id, first_seen_at
                    ) VALUES (?, ?, ?)
                    """,
                    (subscription_id, listing.listing_id, now),
                )
                if cursor.rowcount == 1:
                    newly_discovered.append(listing.listing_id)

        return tuple(newly_discovered)

    def list_pending_notifications(
        self,
        subscription_id: int,
    ) -> tuple[PendingNotification, ...]:
        with self._database.connect() as connection:
            self._require_subscription(connection, subscription_id, allow_deleted=False)
            rows = connection.execute(
                """
                SELECT
                    sl.subscription_id,
                    sl.first_seen_at,
                    l.*,
                    COUNT(ne.id) AS attempt_count
                FROM subscription_listings AS sl
                JOIN listings AS l ON l.listing_id = sl.listing_id
                JOIN subscriptions AS s ON s.id = sl.subscription_id
                LEFT JOIN notification_events AS ne
                    ON ne.subscription_id = sl.subscription_id
                    AND ne.listing_id = sl.listing_id
                WHERE sl.subscription_id = ?
                    AND sl.notified_at IS NULL
                    AND s.status IN ('pending', 'active')
                GROUP BY sl.subscription_id, sl.listing_id
                ORDER BY sl.first_seen_at, sl.listing_id
                """,
                (subscription_id,),
            ).fetchall()

        return tuple(self._pending_notification_from_row(row) for row in rows)

    def record_notification_failure(
        self,
        subscription_id: int,
        listing_id: str,
        *,
        error_code: str,
        error_message: str | None = None,
    ) -> int:
        now = _timestamp(self._clock())
        with self._database.transaction() as connection:
            attempt_count = self._next_attempt_count(
                connection,
                subscription_id,
                listing_id,
                require_pending=True,
            )
            connection.execute(
                """
                INSERT INTO notification_events (
                    subscription_id, listing_id, status, attempt_count,
                    created_at, error_code, error_message
                ) VALUES (?, ?, 'failed', ?, ?, ?, ?)
                """,
                (
                    subscription_id,
                    listing_id,
                    attempt_count,
                    now,
                    error_code,
                    error_message,
                ),
            )
        return attempt_count

    def record_notification_success(
        self,
        subscription_id: int,
        listing_id: str,
    ) -> bool:
        now = _timestamp(self._clock())
        with self._database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE subscription_listings
                SET notified_at = ?
                WHERE subscription_id = ? AND listing_id = ? AND notified_at IS NULL
                """,
                (now, subscription_id, listing_id),
            )
            if cursor.rowcount == 0:
                relation = connection.execute(
                    """
                    SELECT notified_at
                    FROM subscription_listings
                    WHERE subscription_id = ? AND listing_id = ?
                    """,
                    (subscription_id, listing_id),
                ).fetchone()
                if relation is None:
                    raise RepositoryError("subscription listing relation was not found")
                return False

            attempt_count = self._next_attempt_count(
                connection,
                subscription_id,
                listing_id,
                require_pending=False,
            )
            connection.execute(
                """
                INSERT INTO notification_events (
                    subscription_id, listing_id, status, attempt_count,
                    created_at, sent_at
                ) VALUES (?, ?, 'sent', ?, ?, ?)
                """,
                (subscription_id, listing_id, attempt_count, now, now),
            )
        return True

    def create_pending_action(
        self,
        *,
        action_type: str,
        payload: Mapping[str, Any],
        expires_at: datetime,
        subscription_id: int | None = None,
    ) -> PendingAction:
        now = _timestamp(self._clock())
        payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._database.transaction() as connection:
            if subscription_id is not None:
                self._require_subscription(connection, subscription_id, allow_deleted=False)
            cursor = connection.execute(
                """
                INSERT INTO pending_actions (
                    subscription_id, action_type, payload, status, created_at, expires_at
                ) VALUES (?, ?, ?, 'pending', ?, ?)
                """,
                (
                    subscription_id,
                    action_type,
                    payload_json,
                    now,
                    _timestamp(expires_at),
                ),
            )
            action_id = int(cursor.lastrowid)
        return self.get_pending_action(action_id)

    def get_pending_action(self, action_id: int) -> PendingAction:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM pending_actions WHERE id = ?",
                (action_id,),
            ).fetchone()
        if row is None:
            raise RepositoryError(f"pending action {action_id} was not found")
        return self._pending_action_from_row(row)

    def find_latest_pending_action(
        self,
        *,
        action_type: str | None = None,
    ) -> PendingAction | None:
        now = _timestamp(self._clock())
        query = """
            SELECT *
            FROM pending_actions
            WHERE status = 'pending' AND expires_at > ?
        """
        parameters: list[object] = [now]
        if action_type is not None:
            query += " AND action_type = ?"
            parameters.append(action_type)
        query += " ORDER BY id DESC LIMIT 1"

        with self._database.connect() as connection:
            row = connection.execute(query, parameters).fetchone()
        return self._pending_action_from_row(row) if row is not None else None

    def complete_pending_action(self, action_id: int, *, cancel: bool = False) -> bool:
        now = self._clock()
        target_status = "cancelled" if cancel else "consumed"
        with self._database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE pending_actions
                SET status = ?, completed_at = ?
                WHERE id = ? AND status = 'pending' AND expires_at > ?
                """,
                (target_status, _timestamp(now), action_id, _timestamp(now)),
            )
        return cursor.rowcount == 1

    def notification_event_count(
        self,
        subscription_id: int,
        listing_id: str,
        *,
        status: str | None = None,
    ) -> int:
        query = (
            "SELECT COUNT(*) FROM notification_events "
            "WHERE subscription_id = ? AND listing_id = ?"
        )
        parameters: list[object] = [subscription_id, listing_id]
        if status is not None:
            query += " AND status = ?"
            parameters.append(status)
        with self._database.connect() as connection:
            return int(connection.execute(query, parameters).fetchone()[0])

    def record_bot_command_event(
        self,
        *,
        command: str,
        authorized: bool,
        status: str,
        update_id: int | None = None,
        subscription_id: int | None = None,
        error_code: str | None = None,
    ) -> None:
        now = _timestamp(self._clock())
        with self._database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO bot_command_events (
                    update_id, command, authorized, status,
                    subscription_id, created_at, error_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    update_id,
                    command,
                    int(authorized),
                    status,
                    subscription_id,
                    now,
                    error_code,
                ),
            )

    def list_bot_command_events(self) -> tuple[BotCommandEvent, ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM bot_command_events ORDER BY id",
            ).fetchall()
        return tuple(self._bot_command_event_from_row(row) for row in rows)

    def _transition_subscription(
        self,
        subscription_id: int,
        *,
        allowed: set[SubscriptionStatus],
        target: SubscriptionStatus,
    ) -> Subscription:
        now = _timestamp(self._clock())
        current = self.get_subscription(subscription_id)
        if current.status not in allowed:
            raise InvalidSubscriptionStateError(
                f"cannot change subscription from {current.status} to {target}"
            )

        with self._database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE subscriptions
                SET status = ?, updated_at = ?,
                    deleted_at = CASE WHEN ? = 'deleted' THEN ? ELSE deleted_at END
                WHERE id = ? AND status = ?
                """,
                (
                    target.value,
                    now,
                    target.value,
                    now,
                    subscription_id,
                    current.status.value,
                ),
            )
            if cursor.rowcount != 1:
                raise InvalidSubscriptionStateError(
                    "subscription state changed during the operation"
                )
        return self.get_subscription(subscription_id)

    @staticmethod
    def _require_subscription(
        connection: sqlite3.Connection,
        subscription_id: int,
        *,
        allow_deleted: bool,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM subscriptions WHERE id = ?",
            (subscription_id,),
        ).fetchone()
        if row is None or (not allow_deleted and row["status"] == SubscriptionStatus.DELETED):
            raise SubscriptionNotFoundError(f"subscription {subscription_id} was not found")
        return row

    @staticmethod
    def _next_attempt_count(
        connection: sqlite3.Connection,
        subscription_id: int,
        listing_id: str,
        *,
        require_pending: bool,
    ) -> int:
        relation = connection.execute(
            """
            SELECT notified_at
            FROM subscription_listings
            WHERE subscription_id = ? AND listing_id = ?
            """,
            (subscription_id, listing_id),
        ).fetchone()
        if relation is None:
            raise RepositoryError("subscription listing relation was not found")
        if require_pending and relation["notified_at"] is not None:
            raise RepositoryError("listing was already notified")

        count = connection.execute(
            """
            SELECT COUNT(*)
            FROM notification_events
            WHERE subscription_id = ? AND listing_id = ?
            """,
            (subscription_id, listing_id),
        ).fetchone()[0]
        return int(count) + 1

    @staticmethod
    def _subscription_from_row(row: sqlite3.Row) -> Subscription:
        return Subscription(
            id=int(row["id"]),
            name=str(row["name"]),
            source_url=str(row["source_url"]),
            normalized_url=str(row["normalized_url"]),
            status=SubscriptionStatus(row["status"]),
            created_at=_datetime(row["created_at"]),  # type: ignore[arg-type]
            updated_at=_datetime(row["updated_at"]),  # type: ignore[arg-type]
            last_checked_at=_datetime(row["last_checked_at"]),
            last_success_at=_datetime(row["last_success_at"]),
            next_check_at=_datetime(row["next_check_at"]),
            last_result_count=row["last_result_count"],
            deleted_at=_datetime(row["deleted_at"]),
        )

    @staticmethod
    def _pending_notification_from_row(row: sqlite3.Row) -> PendingNotification:
        return PendingNotification(
            subscription_id=int(row["subscription_id"]),
            listing=RentalListing(
                listing_id=str(row["listing_id"]),
                url=str(row["url"]),
                title=str(row["title"]),
                price_monthly=int(row["price_monthly"]),
                location=str(row["location"]),
                category=row["category"],
                layout=row["layout"],
                area_ping=row["area_ping"],
                floor=row["floor"],
                published_text=row["published_text"],
                image_url=row["image_url"],
            ),
            first_seen_at=_datetime(row["first_seen_at"]),  # type: ignore[arg-type]
            attempt_count=int(row["attempt_count"]),
        )

    @staticmethod
    def _pending_action_from_row(row: sqlite3.Row) -> PendingAction:
        return PendingAction(
            id=int(row["id"]),
            subscription_id=row["subscription_id"],
            action_type=str(row["action_type"]),
            payload=json.loads(row["payload"]),
            status=str(row["status"]),
            created_at=_datetime(row["created_at"]),  # type: ignore[arg-type]
            expires_at=_datetime(row["expires_at"]),  # type: ignore[arg-type]
            completed_at=_datetime(row["completed_at"]),
        )

    @staticmethod
    def _bot_command_event_from_row(row: sqlite3.Row) -> BotCommandEvent:
        return BotCommandEvent(
            id=int(row["id"]),
            update_id=row["update_id"],
            command=str(row["command"]),
            authorized=bool(row["authorized"]),
            status=str(row["status"]),
            subscription_id=row["subscription_id"],
            created_at=_datetime(row["created_at"]),  # type: ignore[arg-type]
            error_code=row["error_code"],
        )
