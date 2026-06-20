"""Run the rental monitoring scheduler until interrupted."""

from __future__ import annotations

import logging

from rental_alert_bot.config import Settings
from rental_alert_bot.database import Database
from rental_alert_bot.logging_config import configure_logging
from rental_alert_bot.monitoring_service import MonitoringService, MonitoringSettings
from rental_alert_bot.rental_client import RentalClient
from rental_alert_bot.repository import RentalRepository
from rental_alert_bot.scheduler import (
    MonitoringScheduler,
    SchedulerSettings,
    install_stop_signal_handlers,
)
from rental_alert_bot.telegram_client import TelegramClient


def main() -> int:
    settings = Settings.from_environment(require_secrets=True)
    configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)

    database = Database(settings.database_path)
    database.initialize()
    repository = RentalRepository(database)
    service_run = repository.record_service_start(process_name="monitor_loop")
    stop_status = "stopped"
    stop_error: str | None = None

    try:
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
            scheduler = MonitoringScheduler(
                monitor=monitor,
                settings=SchedulerSettings(),
                logger=logger,
            )
            install_stop_signal_handlers(scheduler)
            logger.info(
                "monitor_scheduler_started",
                extra={
                    "poll_interval_seconds": settings.poll_interval_seconds,
                    "poll_jitter_seconds": settings.poll_jitter_seconds,
                },
            )
            scheduler.run_forever()
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


if __name__ == "__main__":
    raise SystemExit(main())
