from rental_alert_bot.telegram_client import TelegramApiError
from rental_alert_bot.telegram_models import TelegramUpdate
from rental_alert_bot.telegram_polling_service import (
    TelegramPollingService,
    TelegramPollingSettings,
)


class FakeTelegram:
    def __init__(
        self,
        updates: tuple[TelegramUpdate, ...] = (),
        *,
        error: TelegramApiError | None = None,
    ) -> None:
        self.updates = updates
        self.error = error
        self.calls: list[tuple[int | None, int]] = []

    def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout_seconds: int = 30,
    ) -> tuple[TelegramUpdate, ...]:
        self.calls.append((offset, timeout_seconds))
        if self.error is not None:
            raise self.error
        return self.updates


class FakeHandler:
    def __init__(self, *, fail_update_id: int | None = None) -> None:
        self.handled_update_ids: list[int] = []
        self.fail_update_id = fail_update_id

    def handle_update(self, update: TelegramUpdate) -> None:
        self.handled_update_ids.append(update.update_id)
        if update.update_id == self.fail_update_id:
            raise RuntimeError("handler failed")


def update(update_id: int) -> TelegramUpdate:
    return TelegramUpdate.from_api(
        {
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "chat": {"id": 123, "type": "private"},
                "from": {"id": 456, "is_bot": False, "first_name": "KC"},
                "text": "/start",
            },
        }
    )


def test_poll_once_handles_updates_and_advances_offset() -> None:
    telegram = FakeTelegram((update(10), update(11)))
    handler = FakeHandler()
    polling = TelegramPollingService(
        telegram=telegram,
        handler=handler,
        settings=TelegramPollingSettings(long_poll_timeout_seconds=9),
    )

    count = polling.poll_once()

    assert count == 2
    assert handler.handled_update_ids == [10, 11]
    assert polling.offset == 12
    assert telegram.calls == [(None, 9)]


def test_poll_once_advances_offset_when_handler_fails() -> None:
    telegram = FakeTelegram((update(10),))
    handler = FakeHandler(fail_update_id=10)
    polling = TelegramPollingService(telegram=telegram, handler=handler)

    count = polling.poll_once()

    assert count == 1
    assert polling.offset == 11


def test_poll_once_sleeps_after_get_updates_failure() -> None:
    delays: list[float] = []
    telegram = FakeTelegram(error=TelegramApiError("failed"))
    polling = TelegramPollingService(
        telegram=telegram,
        handler=FakeHandler(),
        settings=TelegramPollingSettings(error_sleep_seconds=2),
        sleep=delays.append,
    )

    count = polling.poll_once()

    assert count == 0
    assert delays == [2]
