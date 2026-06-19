"""Run the Telegram command handler with long polling for manual validation."""

from __future__ import annotations

import logging

from rental_alert_bot.bot_service import BotService, BotServiceSettings
from rental_alert_bot.config import Settings
from rental_alert_bot.database import Database
from rental_alert_bot.logging_config import configure_logging
from rental_alert_bot.rental_client import RentalClient
from rental_alert_bot.repository import RentalRepository
from rental_alert_bot.telegram_client import TelegramClient
from rental_alert_bot.telegram_polling_service import TelegramPollingService


def main() -> int:
    settings = Settings.from_environment(require_secrets=True)
    configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)
    database = Database(settings.database_path)
    database.initialize()
    repository = RentalRepository(database)

    with TelegramClient(
        settings.telegram_bot_token,
        timeout_seconds=settings.request_timeout_seconds,
    ) as telegram, RentalClient(
        timeout_seconds=settings.request_timeout_seconds,
    ) as rental_client:
        service = BotService(
            repository=repository,
            telegram=telegram,
            rental_fetcher=rental_client,
            settings=BotServiceSettings(
                authorized_user_id=settings.authorized_telegram_user_id,
                initial_notification_batch_size=settings.initial_notification_batch_size,
                send_delay_seconds=settings.telegram_send_delay_seconds,
            ),
        )
        logger.info("telegram_bot_polling_started")
        TelegramPollingService(telegram=telegram, handler=service, logger=logger).run_forever()


if __name__ == "__main__":
    raise SystemExit(main())
