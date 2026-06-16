"""Telegram command handling for the personal rental alert bot."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from rental_alert_bot.listing import RentalSearchPage
from rental_alert_bot.message_templates import (
    HELP_TEXT,
    listing_notification,
    subscription_created_message,
    subscriptions_message,
    test_result_message,
    unauthorized_message,
)
from rental_alert_bot.rental_parser import RentalPageError
from rental_alert_bot.rental_url import RentalUrlError, normalize_rental_search_url
from rental_alert_bot.repository import (
    DuplicateSubscriptionError,
    InvalidSubscriptionStateError,
    PendingAction,
    RentalRepository,
    RepositoryError,
)
from rental_alert_bot.telegram_client import TelegramApiError
from rental_alert_bot.telegram_models import TelegramMessage, TelegramUpdate


class TelegramSender(Protocol):
    def send_message(self, chat_id: int, text: str) -> None: ...


class RentalFetcher(Protocol):
    def fetch(self, raw_url: str) -> RentalSearchPage: ...


@dataclass(frozen=True, slots=True)
class BotServiceSettings:
    authorized_user_id: int
    initial_notification_batch_size: int = 10
    send_delay_seconds: float = 1.2
    pending_action_ttl_minutes: int = 30


class BotService:
    def __init__(
        self,
        *,
        repository: RentalRepository,
        telegram: TelegramSender,
        rental_fetcher: RentalFetcher,
        settings: BotServiceSettings,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._telegram = telegram
        self._rental_fetcher = rental_fetcher
        self._settings = settings
        self._sleep = sleep
        self._clock = clock

    def handle_update(self, update: TelegramUpdate) -> None:
        if update.message is None:
            return

        message = update.message
        command_label = _command_label(message.text)
        authorized = self._is_authorized(message)
        event_status = "accepted"
        error_code: str | None = None

        if not self._is_authorized(message):
            self._telegram.send_message(message.chat.id, unauthorized_message())
            self._record_command_event(
                update_id=update.update_id,
                command=command_label,
                authorized=False,
                status="rejected",
            )
            return

        text = (message.text or "").strip()
        if not text:
            self._telegram.send_message(message.chat.id, "請傳送文字指令或 591 搜尋網址。")
            self._record_command_event(
                update_id=update.update_id,
                command=command_label,
                authorized=authorized,
                status="failed",
                error_code="empty_text",
            )
            return

        command, argument = _parse_command(text)
        try:
            if command in {"/start", "/help"}:
                self._telegram.send_message(message.chat.id, HELP_TEXT)
            elif command == "/subscriptions":
                self._telegram.send_message(
                    message.chat.id,
                    subscriptions_message(self._repository.list_subscriptions()),
                )
            elif command == "/pause":
                self._handle_pause(message, argument)
            elif command == "/resume":
                self._handle_resume(message, argument)
            elif command == "/delete":
                self._handle_delete_request(message, argument)
            elif command == "/test":
                self._handle_test(message, argument)
            elif command == "/cancel":
                self._handle_cancel(message)
            elif (
                command is None
                and not text.startswith("https://")
                and self._has_pending_subscription_id_request()
            ):
                self._handle_pending_subscription_id(message, text)
            elif _is_confirmation(text):
                self._handle_confirmation(message)
            elif text.startswith("https://"):
                self._handle_search_url(message, text)
            elif command:
                self._telegram.send_message(message.chat.id, "未知指令。輸入 /help 查看用法。")
            else:
                self._telegram.send_message(
                    message.chat.id,
                    "我只接受 591 租屋搜尋網址或 /help 中列出的指令。",
                )
        except RentalUrlError:
            event_status = "failed"
            error_code = "rental_url_error"
            self._telegram.send_message(
                message.chat.id,
                "操作失敗：請貼上 591 租屋搜尋結果頁網址，例如 "
                "https://rent.591.com.tw/list?region=1。短網址或分享連結目前不支援。",
            )
        except RentalPageError as exc:
            event_status = "failed"
            error_code = "rental_page_error"
            self._telegram.send_message(message.chat.id, f"讀取 591 失敗：{exc}")
        except (RepositoryError, InvalidSubscriptionStateError) as exc:
            event_status = "failed"
            error_code = "repository_error"
            self._telegram.send_message(message.chat.id, f"操作失敗：{exc}")
        finally:
            self._record_command_event(
                update_id=update.update_id,
                command=command_label,
                authorized=authorized,
                status=event_status,
                error_code=error_code,
            )

    def _is_authorized(self, message: TelegramMessage) -> bool:
        return (
            message.from_user is not None
            and message.from_user.id == self._settings.authorized_user_id
        )

    def _handle_search_url(self, message: TelegramMessage, raw_url: str) -> None:
        normalized_url = normalize_rental_search_url(raw_url)
        page = self._rental_fetcher.fetch(normalized_url)

        try:
            subscription = self._repository.create_subscription(
                name=f"搜尋條件 {self._clock().strftime('%m%d-%H%M')}",
                source_url=raw_url,
                normalized_url=normalized_url,
            )
        except DuplicateSubscriptionError:
            self._telegram.send_message(message.chat.id, "這組搜尋條件已經存在。")
            return

        listing_ids = self._repository.record_discovered_listings(subscription.id, page.listings)
        self._repository.create_pending_action(
            subscription_id=subscription.id,
            action_type="confirm_initial_delivery",
            payload={
                "subscription_id": subscription.id,
                "listing_ids": list(listing_ids),
                "total_count": page.total_count,
            },
            expires_at=self._expires_at(),
        )
        self._telegram.send_message(
            message.chat.id,
            subscription_created_message(subscription.id, page.total_count, len(page.listings)),
        )

    def _handle_pause(self, message: TelegramMessage, argument: str) -> None:
        if not argument:
            self._request_subscription_id(message, "pause")
            return

        self._pause_by_id(message, _required_id(argument))

    def _pause_by_id(self, message: TelegramMessage, subscription_id: int) -> None:
        self._repository.get_live_subscription(subscription_id)
        subscription = self._repository.pause_subscription(subscription_id)
        self._telegram.send_message(message.chat.id, f"已暫停訂閱 #{subscription.id}。")

    def _handle_resume(self, message: TelegramMessage, argument: str) -> None:
        if not argument:
            self._request_subscription_id(message, "resume")
            return

        self._resume_by_id(message, _required_id(argument))

    def _resume_by_id(self, message: TelegramMessage, subscription_id: int) -> None:
        self._repository.get_live_subscription(subscription_id)
        subscription = self._repository.resume_subscription(subscription_id)
        self._telegram.send_message(message.chat.id, f"已恢復訂閱 #{subscription.id}。")

    def _handle_delete_request(self, message: TelegramMessage, argument: str) -> None:
        if not argument:
            self._request_subscription_id(message, "delete")
            return

        self._request_delete_confirmation(message, _required_id(argument))

    def _request_delete_confirmation(self, message: TelegramMessage, subscription_id: int) -> None:
        subscription = self._repository.get_live_subscription(subscription_id)
        self._repository.create_pending_action(
            subscription_id=subscription.id,
            action_type="confirm_delete",
            payload={"subscription_id": subscription.id},
            expires_at=self._expires_at(),
        )
        self._telegram.send_message(
            message.chat.id,
            f"即將刪除訂閱 #{subscription.id} {subscription.name}。\n"
            "請回覆「確認」完成刪除，或輸入 /cancel 取消。",
        )

    def _handle_test(self, message: TelegramMessage, argument: str) -> None:
        if not argument:
            self._request_subscription_id(message, "test")
            return

        self._test_by_id(message, _required_id(argument))

    def _test_by_id(self, message: TelegramMessage, subscription_id: int) -> None:
        subscription = self._repository.get_live_subscription(subscription_id)
        page = self._rental_fetcher.fetch(subscription.normalized_url)
        self._telegram.send_message(
            message.chat.id,
            test_result_message(subscription.id, page.total_count, len(page.listings)),
        )

    def _request_subscription_id(self, message: TelegramMessage, operation: str) -> None:
        self._repository.create_pending_action(
            action_type="await_subscription_id",
            payload={"operation": operation},
            expires_at=self._expires_at(),
        )
        self._telegram.send_message(
            message.chat.id,
            f"{_operation_label(operation)}：請輸入訂閱編號，或輸入 /cancel 取消。",
        )

    def _has_pending_subscription_id_request(self) -> bool:
        return (
            self._repository.find_latest_pending_action(
                action_type="await_subscription_id",
            )
            is not None
        )

    def _handle_pending_subscription_id(self, message: TelegramMessage, text: str) -> None:
        action = self._repository.find_latest_pending_action(
            action_type="await_subscription_id",
        )
        if action is None:
            self._telegram.send_message(message.chat.id, "目前沒有等待輸入編號的動作。")
            return

        try:
            subscription_id = _required_id(text)
        except RepositoryError:
            self._telegram.send_message(
                message.chat.id,
                "請輸入訂閱編號（數字），或輸入 /cancel 取消。",
            )
            return

        operation = str(action.payload.get("operation", ""))
        if operation == "pause":
            self._pause_by_id(message, subscription_id)
        elif operation == "resume":
            self._resume_by_id(message, subscription_id)
        elif operation == "delete":
            self._request_delete_confirmation(message, subscription_id)
        elif operation == "test":
            self._test_by_id(message, subscription_id)
        else:
            self._telegram.send_message(message.chat.id, "未知的等待動作，請輸入 /cancel。")
            return

        self._repository.complete_pending_action(action.id)

    def _handle_cancel(self, message: TelegramMessage) -> None:
        action = self._repository.find_latest_pending_action()
        if action is None:
            self._telegram.send_message(message.chat.id, "目前沒有等待確認的動作。")
            return

        if action.action_type == "confirm_initial_delivery" and action.subscription_id is not None:
            self._repository.delete_subscription(action.subscription_id)
        self._repository.complete_pending_action(action.id, cancel=True)
        self._telegram.send_message(message.chat.id, "已取消目前等待確認的動作。")

    def _handle_confirmation(self, message: TelegramMessage) -> None:
        action = self._repository.find_latest_pending_action()
        if action is None:
            self._telegram.send_message(message.chat.id, "目前沒有等待確認的動作。")
            return

        if action.action_type == "confirm_initial_delivery":
            self._deliver_initial_listings(message, action)
        elif action.action_type == "confirm_delete":
            subscription_id = int(action.payload["subscription_id"])
            self._repository.delete_subscription(subscription_id)
            self._repository.complete_pending_action(action.id)
            self._telegram.send_message(message.chat.id, f"已刪除訂閱 #{subscription_id}。")
        else:
            self._telegram.send_message(message.chat.id, "未知的確認動作，請輸入 /cancel。")

    def _deliver_initial_listings(
        self,
        message: TelegramMessage,
        action: PendingAction,
    ) -> None:
        subscription_id = int(action.payload["subscription_id"])
        target_ids = set(action.payload.get("listing_ids", []))
        sent_count = 0

        for pending in self._repository.list_pending_notifications(subscription_id):
            latest_action = self._repository.get_pending_action(action.id)
            if latest_action.status != "pending":
                self._telegram.send_message(message.chat.id, "全量通知已取消。")
                return
            if target_ids and pending.listing.listing_id not in target_ids:
                continue

            try:
                self._telegram.send_message(
                    message.chat.id,
                    listing_notification(pending.listing),
                )
            except TelegramApiError as exc:
                self._repository.record_notification_failure(
                    subscription_id,
                    pending.listing.listing_id,
                    error_code=f"telegram_{exc.error_code or 'error'}",
                    error_message=str(exc),
                )
                raise

            self._repository.record_notification_success(
                subscription_id,
                pending.listing.listing_id,
            )
            sent_count += 1
            if sent_count % self._settings.initial_notification_batch_size == 0:
                self._sleep(self._settings.send_delay_seconds)

        self._repository.activate_subscription(subscription_id)
        self._repository.complete_pending_action(action.id)
        self._telegram.send_message(
            message.chat.id,
            f"首次全量通知完成，共發送 {sent_count} 筆。之後只會通知新房源。",
        )

    def _expires_at(self) -> datetime:
        return self._clock() + timedelta(minutes=self._settings.pending_action_ttl_minutes)

    def _record_command_event(
        self,
        *,
        update_id: int,
        command: str,
        authorized: bool,
        status: str,
        error_code: str | None = None,
    ) -> None:
        self._repository.record_bot_command_event(
            update_id=update_id,
            command=command,
            authorized=authorized,
            status=status,
            error_code=error_code,
        )


def _parse_command(text: str) -> tuple[str | None, str]:
    if not text.startswith("/"):
        return None, ""

    first, _, rest = text.partition(" ")
    command = first.split("@", 1)[0].lower()
    return command, rest.strip()


def _command_label(text: str | None) -> str:
    value = (text or "").strip()
    if not value:
        return "empty"
    command, _argument = _parse_command(value)
    if command:
        return command
    if _is_confirmation(value):
        return "confirm"
    if value.startswith("https://"):
        return "url"
    return "text"


def _required_id(argument: str) -> int:
    if not argument:
        raise RepositoryError("請提供訂閱編號")
    try:
        value = int(argument)
    except ValueError as exc:
        raise RepositoryError("訂閱編號必須是數字") from exc
    if value <= 0:
        raise RepositoryError("訂閱編號必須大於 0")
    return value


def _is_confirmation(text: str) -> bool:
    return text.strip().lower() in {"確認", "confirm", "yes", "y"}


def _operation_label(operation: str) -> str:
    labels = {
        "pause": "暫停訂閱",
        "resume": "恢復訂閱",
        "delete": "刪除訂閱",
        "test": "測試訂閱",
    }
    return labels.get(operation, "操作")
