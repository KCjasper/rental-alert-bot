"""Run the Telegram command handler with long polling for manual validation."""

from __future__ import annotations

from rental_alert_bot.bot_service import BotService, BotServiceSettings
from rental_alert_bot.config import Settings
from rental_alert_bot.database import Database
from rental_alert_bot.rental_client import RentalClient
from rental_alert_bot.repository import RentalRepository
from rental_alert_bot.telegram_client import TelegramClient


def main() -> int:
    settings = Settings.from_environment(require_secrets=True)
    database = Database(settings.database_path)
    database.initialize()
    repository = RentalRepository(database)

    offset: int | None = None
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
        while True:
            updates = telegram.get_updates(offset=offset, timeout_seconds=30)
            for update in updates:
                service.handle_update(update)
                offset = update.update_id + 1


if __name__ == "__main__":
    raise SystemExit(main())
