import signal

from rental_alert_bot.monitoring_service import SubscriptionCheckResult
from rental_alert_bot.scheduler import (
    MonitoringScheduler,
    SchedulerSettings,
    install_stop_signal_handlers,
)


class FakeMonitor:
    def __init__(self) -> None:
        self.calls = 0

    def check_due_subscriptions(self) -> tuple[SubscriptionCheckResult, ...]:
        self.calls += 1
        return (
            SubscriptionCheckResult(
                subscription_id=1,
                fetched_count=1,
                discovered_count=1,
                sent_count=1,
                failed_count=0,
                succeeded=True,
            ),
        )


def test_scheduler_runs_until_max_iterations() -> None:
    monitor = FakeMonitor()
    scheduler = MonitoringScheduler(
        monitor=monitor,  # type: ignore[arg-type]
        settings=SchedulerSettings(idle_sleep_seconds=0.001),
    )

    iterations = scheduler.run_forever(max_iterations=3)

    assert iterations == 3
    assert monitor.calls == 3


def test_scheduler_does_not_run_after_stop() -> None:
    monitor = FakeMonitor()
    scheduler = MonitoringScheduler(
        monitor=monitor,  # type: ignore[arg-type]
        settings=SchedulerSettings(idle_sleep_seconds=0.001),
    )
    scheduler.stop()

    iterations = scheduler.run_forever()

    assert iterations == 0
    assert monitor.calls == 0


def test_stop_signal_handler_requests_scheduler_stop(monkeypatch) -> None:
    captured_handlers = []

    def fake_signal(_signal_number, handler):
        captured_handlers.append(handler)

    monkeypatch.setattr(signal, "signal", fake_signal)
    scheduler = MonitoringScheduler(
        monitor=FakeMonitor(),  # type: ignore[arg-type]
        settings=SchedulerSettings(idle_sleep_seconds=0.001),
    )

    install_stop_signal_handlers(scheduler, signals=(signal.SIGTERM,))
    captured_handlers[0](signal.SIGTERM.value, None)

    assert scheduler.stop_event.is_set()
