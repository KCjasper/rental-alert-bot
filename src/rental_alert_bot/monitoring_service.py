"""Scheduled rental monitoring and notification orchestration."""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from rental_alert_bot.listing import RentalListing, RentalSearchPage
from rental_alert_bot.message_templates import listing_notification
from rental_alert_bot.rental_parser import RentalPageError
from rental_alert_bot.repository import RentalRepository, Subscription
from rental_alert_bot.telegram_client import TelegramApiError


class TelegramSender(Protocol):
    def send_message(self, chat_id: int, text: str) -> None: ...

    def send_photo(self, chat_id: int, photo_url: str, caption: str) -> None: ...


class RentalFetcher(Protocol):
    def fetch(self, raw_url: str) -> RentalSearchPage: ...


@dataclass(frozen=True, slots=True)
class MonitoringSettings:
    alert_chat_id: int
    poll_interval_seconds: int = 300
    poll_jitter_seconds: int = 30
    failure_alert_threshold: int = 3

    def __post_init__(self) -> None:
        if self.alert_chat_id <= 0:
            raise ValueError("alert_chat_id must be greater than zero")
        if self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be greater than zero")
        if self.poll_jitter_seconds < 0:
            raise ValueError("poll_jitter_seconds must be zero or greater")
        if self.failure_alert_threshold <= 0:
            raise ValueError("failure_alert_threshold must be greater than zero")


@dataclass(frozen=True, slots=True)
class SubscriptionCheckResult:
    subscription_id: int
    fetched_count: int
    discovered_count: int
    sent_count: int
    failed_count: int
    succeeded: bool
    error_message: str | None = None


@dataclass(slots=True)
class MonitoringService:
    repository: RentalRepository
    telegram: TelegramSender
    rental_fetcher: RentalFetcher
    settings: MonitoringSettings
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    random_integer: Callable[[int, int], int] = random.randint
    _consecutive_failures: dict[int, int] = field(default_factory=dict)

    def check_due_subscriptions(self) -> tuple[SubscriptionCheckResult, ...]:
        started_at = self.clock()
        try:
            results = tuple(
                self.check_subscription(subscription)
                for subscription in self.repository.list_due_subscriptions(started_at)
            )
        except Exception as exc:
            self.repository.record_monitor_run(
                started_at=started_at,
                completed_at=self.clock(),
                checked_count=0,
                succeeded_count=0,
                failed_count=0,
                sent_count=0,
                notification_failed_count=0,
                status="failed",
                error_code=exc.__class__.__name__,
                error_message=str(exc),
            )
            raise

        self.repository.record_monitor_run(
            started_at=started_at,
            completed_at=self.clock(),
            checked_count=len(results),
            succeeded_count=sum(1 for result in results if result.succeeded),
            failed_count=sum(1 for result in results if not result.succeeded),
            sent_count=sum(result.sent_count for result in results),
            notification_failed_count=sum(result.failed_count for result in results),
            status="completed",
        )
        return results

    def check_subscription(self, subscription: Subscription) -> SubscriptionCheckResult:
        next_check_at = self._next_check_at()
        try:
            page = self.rental_fetcher.fetch(subscription.normalized_url)
        except RentalPageError as exc:
            self.repository.record_check(
                subscription.id,
                result_count=0,
                succeeded=False,
                next_check_at=next_check_at,
            )
            self._record_subscription_failure(subscription, exc)
            return SubscriptionCheckResult(
                subscription_id=subscription.id,
                fetched_count=0,
                discovered_count=0,
                sent_count=0,
                failed_count=0,
                succeeded=False,
                error_message=str(exc),
            )

        discovered_ids = self.repository.record_discovered_listings(
            subscription.id,
            page.listings,
        )
        self.repository.record_check(
            subscription.id,
            result_count=page.total_count,
            succeeded=True,
            next_check_at=next_check_at,
        )
        self._consecutive_failures.pop(subscription.id, None)
        sent_count, failed_count = self._send_pending_notifications(subscription.id)

        return SubscriptionCheckResult(
            subscription_id=subscription.id,
            fetched_count=len(page.listings),
            discovered_count=len(discovered_ids),
            sent_count=sent_count,
            failed_count=failed_count,
            succeeded=True,
        )

    def _send_pending_notifications(self, subscription_id: int) -> tuple[int, int]:
        sent_count = 0
        failed_count = 0
        for pending in self.repository.list_pending_notifications(subscription_id):
            if not self._send_listing_notification(subscription_id, pending.listing):
                failed_count += 1
                continue

            self.repository.record_notification_success(
                subscription_id,
                pending.listing.listing_id,
            )
            sent_count += 1

        return sent_count, failed_count

    def _send_listing_notification(self, subscription_id: int, listing: RentalListing) -> bool:
        text = listing_notification(listing)
        if listing.image_url:
            try:
                self.telegram.send_photo(
                    self.settings.alert_chat_id,
                    listing.image_url,
                    text,
                )
                return True
            except TelegramApiError as exc:
                self.repository.record_notification_failure(
                    subscription_id,
                    listing.listing_id,
                    error_code=f"telegram_photo_{exc.error_code or 'error'}",
                    error_message=str(exc),
                )

        try:
            self.telegram.send_message(self.settings.alert_chat_id, text)
        except TelegramApiError as exc:
            self.repository.record_notification_failure(
                subscription_id,
                listing.listing_id,
                error_code=f"telegram_{exc.error_code or 'error'}",
                error_message=str(exc),
            )
            return False

        return True

    def _record_subscription_failure(
        self,
        subscription: Subscription,
        exc: RentalPageError,
    ) -> None:
        failure_count = self._consecutive_failures.get(subscription.id, 0) + 1
        self._consecutive_failures[subscription.id] = failure_count
        if failure_count < self.settings.failure_alert_threshold:
            return

        self.telegram.send_message(
            self.settings.alert_chat_id,
            "\n".join(
                [
                    "系統告警：591 搜尋檢查連續失敗",
                    f"訂閱：#{subscription.id} {subscription.name}",
                    f"連續失敗次數：{failure_count}",
                    f"錯誤：{exc}",
                ]
            ),
        )

    def _next_check_at(self) -> datetime:
        jitter = (
            self.random_integer(0, self.settings.poll_jitter_seconds)
            if self.settings.poll_jitter_seconds
            else 0
        )
        return self.clock() + timedelta(
            seconds=self.settings.poll_interval_seconds + jitter,
        )
