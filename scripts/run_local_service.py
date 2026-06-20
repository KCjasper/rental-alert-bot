"""Run Telegram commands and rental monitoring in one local process."""

from __future__ import annotations

import logging
import signal
import threading

from rental_alert_bot.bot_service import BotService, BotServiceSettings
from rental_alert_bot.config import Settings
from rental_alert_bot.database import Database
from rental_alert_bot.logging_config import configure_logging
from rental_alert_bot.monitoring_service import MonitoringService, MonitoringSettings
from rental_alert_bot.rental_client import RentalClient
from rental_alert_bot.repository import RentalRepository
from rental_alert_bot.scheduler import MonitoringScheduler, SchedulerSettings
from rental_alert_bot.telegram_client import TelegramClient
from rental_alert_bot.telegram_polling_service import TelegramPollingService


def main() -> int:
    settings = Settings.from_environment(require_secrets=True)
    configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)

    database = Database(settings.database_path)
    database.initialize()
    repository = RentalRepository(database)
    service_run = repository.record_service_start(process_name="local_service")
    stop_status = "stopped"
    stop_error: str | None = None

    try:
        with (
            TelegramClient(
                settings.telegram_bot_token,
                timeout_seconds=settings.request_timeout_seconds,
            ) as bot_telegram,
            TelegramClient(
                settings.telegram_bot_token,
                timeout_seconds=settings.request_timeout_seconds,
            ) as monitor_telegram,
            RentalClient(timeout_seconds=settings.request_timeout_seconds) as bot_fetcher,
            RentalClient(timeout_seconds=settings.request_timeout_seconds) as monitor_fetcher,
        ):
            bot = BotService(
                repository=repository,
                telegram=bot_telegram,
                rental_fetcher=bot_fetcher,
                settings=BotServiceSettings(
                    authorized_user_id=settings.authorized_telegram_user_id,
                    initial_notification_batch_size=settings.initial_notification_batch_size,
                    send_delay_seconds=settings.telegram_send_delay_seconds,
                ),
            )
            monitor = MonitoringService(
                repository=repository,
                telegram=monitor_telegram,
                rental_fetcher=monitor_fetcher,
                settings=MonitoringSettings(
                    alert_chat_id=settings.authorized_telegram_user_id,
                    poll_interval_seconds=settings.poll_interval_seconds,
                    poll_jitter_seconds=settings.poll_jitter_seconds,
                    failure_alert_threshold=settings.failure_alert_threshold,
                ),
            )
            scheduler = MonitoringScheduler(
                monitor=monitor,
                settings=SchedulerSettings(),
                logger=logger,
            )
            polling = TelegramPollingService(
                telegram=bot_telegram,
                handler=bot,
                logger=logger,
            )
            _install_stop_handlers(scheduler, polling, logger)

            scheduler_thread = threading.Thread(
                target=scheduler.run_forever,
                name="rental-monitor-scheduler",
                daemon=True,
            )
            scheduler_thread.start()
            logger.info("local_service_started")
            try:
                polling.run_forever()
            finally:
                scheduler.stop()
                scheduler_thread.join(timeout=10)
                logger.info("local_service_stopped")
    except Exception as exc:
        stop_status = "failed"
        stop_error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        try:
            repository.record_service_stop(
                service_run.id,
                status=stop_status,
                stop_reason="process_exit",
                error_message=stop_error,
            )
        except Exception:
            logger.exception("service_run_stop_record_failed")

    return 0


def _install_stop_handlers(
    scheduler: MonitoringScheduler,
    polling: TelegramPollingService,
    logger: logging.Logger,
) -> None:
    def request_stop(signum: int, _frame: object) -> None:
        logger.info("local_service_stop_requested", extra={"signal": signum})
        scheduler.stop()
        polling.stop()

    for item in (signal.SIGINT, signal.SIGTERM):
        signal.signal(item, request_stop)


if __name__ == "__main__":
    raise SystemExit(main())
