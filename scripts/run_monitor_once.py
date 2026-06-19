"""Run one scheduled monitoring pass for due active subscriptions."""

from __future__ import annotations

import logging

from rental_alert_bot.config import Settings
from rental_alert_bot.database import Database
from rental_alert_bot.logging_config import configure_logging
from rental_alert_bot.monitoring_service import MonitoringService, MonitoringSettings
from rental_alert_bot.rental_client import RentalClient
from rental_alert_bot.repository import RentalRepository
from rental_alert_bot.telegram_client import TelegramClient


def main() -> int:
    settings = Settings.from_environment(require_secrets=True)
    configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)

    database = Database(settings.database_path)
    database.initialize()
    repository = RentalRepository(database)

    with (
        TelegramClient(
            settings.telegram_bot_token,
            timeout_seconds=settings.request_timeout_seconds,
        ) as telegram,
        RentalClient(timeout_seconds=settings.request_timeout_seconds) as rental_fetcher,
    ):
        monitor = MonitoringService(
            repository=repository,
            telegram=telegram,
            rental_fetcher=rental_fetcher,
            settings=MonitoringSettings(
                alert_chat_id=settings.authorized_telegram_user_id,
                poll_interval_seconds=settings.poll_interval_seconds,
                poll_jitter_seconds=settings.poll_jitter_seconds,
                failure_alert_threshold=settings.failure_alert_threshold,
            ),
        )
        results = monitor.check_due_subscriptions()

    logger.info(
        "monitor_once_completed",
        extra={
            "checked_count": len(results),
            "sent_count": sum(result.sent_count for result in results),
            "failed_count": sum(result.failed_count for result in results),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
