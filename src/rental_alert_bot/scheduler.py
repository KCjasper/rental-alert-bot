"""Long-running monitoring scheduler with graceful stop support."""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field

from rental_alert_bot.monitoring_service import MonitoringService, SubscriptionCheckResult


@dataclass(frozen=True, slots=True)
class SchedulerSettings:
    idle_sleep_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.idle_sleep_seconds <= 0:
            raise ValueError("idle_sleep_seconds must be greater than zero")


@dataclass(slots=True)
class MonitoringScheduler:
    monitor: MonitoringService
    settings: SchedulerSettings = SchedulerSettings()
    stop_event: threading.Event = field(default_factory=threading.Event)
    logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger(__name__),
    )

    def run_once(self) -> tuple[SubscriptionCheckResult, ...]:
        results = self.monitor.check_due_subscriptions()
        self.logger.info(
            "monitor_scheduler_iteration_completed",
            extra={
                "checked_count": len(results),
                "sent_count": sum(result.sent_count for result in results),
                "failed_count": sum(result.failed_count for result in results),
            },
        )
        return results

    def run_forever(self, *, max_iterations: int | None = None) -> int:
        iterations = 0
        while not self.stop_event.is_set():
            self.run_once()
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break
            self.stop_event.wait(self.settings.idle_sleep_seconds)

        self.logger.info(
            "monitor_scheduler_stopped",
            extra={"iterations": iterations},
        )
        return iterations

    def stop(self) -> None:
        self.stop_event.set()


def install_stop_signal_handlers(
    scheduler: MonitoringScheduler,
    *,
    signals: Sequence[signal.Signals] = (signal.SIGINT, signal.SIGTERM),
) -> None:
    def request_stop(signum: int, _frame: object) -> None:
        scheduler.logger.info(
            "monitor_scheduler_stop_requested",
            extra={"signal": signum},
        )
        scheduler.stop()

    for item in signals:
        signal.signal(item, request_stop)
