"""Telegram long-polling loop with graceful stop support."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from rental_alert_bot.telegram_client import TelegramApiError
from rental_alert_bot.telegram_models import TelegramUpdate


class TelegramUpdateSource(Protocol):
    def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout_seconds: int = 30,
    ) -> tuple[TelegramUpdate, ...]: ...


class TelegramUpdateHandler(Protocol):
    def handle_update(self, update: TelegramUpdate) -> None: ...


@dataclass(frozen=True, slots=True)
class TelegramPollingSettings:
    long_poll_timeout_seconds: int = 30
    error_sleep_seconds: float = 5

    def __post_init__(self) -> None:
        if self.long_poll_timeout_seconds <= 0:
            raise ValueError("long_poll_timeout_seconds must be greater than zero")
        if self.error_sleep_seconds <= 0:
            raise ValueError("error_sleep_seconds must be greater than zero")


@dataclass(slots=True)
class TelegramPollingService:
    telegram: TelegramUpdateSource
    handler: TelegramUpdateHandler
    settings: TelegramPollingSettings = TelegramPollingSettings()
    stop_event: threading.Event = field(default_factory=threading.Event)
    sleep: Callable[[float], None] = time.sleep
    logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger(__name__),
    )
    offset: int | None = None

    def poll_once(self) -> int:
        try:
            updates = self.telegram.get_updates(
                offset=self.offset,
                timeout_seconds=self.settings.long_poll_timeout_seconds,
            )
        except TelegramApiError:
            self.logger.exception("telegram_get_updates_failed")
            self.sleep(self.settings.error_sleep_seconds)
            return 0

        handled_count = 0
        for update in updates:
            try:
                self.handler.handle_update(update)
            except Exception:
                self.logger.exception(
                    "telegram_update_handling_failed",
                    extra={"update_id": update.update_id},
                )
            finally:
                self.offset = update.update_id + 1
            handled_count += 1

        return handled_count

    def run_forever(self, *, max_iterations: int | None = None) -> int:
        iterations = 0
        while not self.stop_event.is_set():
            self.poll_once()
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break

        self.logger.info(
            "telegram_polling_stopped",
            extra={"iterations": iterations, "offset": self.offset},
        )
        return iterations

    def stop(self) -> None:
        self.stop_event.set()
