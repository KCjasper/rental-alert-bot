"""Small Telegram Bot API data models used by the command handler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TelegramUser:
    id: int
    is_bot: bool
    first_name: str | None = None
    username: str | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> TelegramUser:
        return cls(
            id=int(payload["id"]),
            is_bot=bool(payload.get("is_bot", False)),
            first_name=payload.get("first_name"),
            username=payload.get("username"),
        )


@dataclass(frozen=True, slots=True)
class TelegramChat:
    id: int
    type: str

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> TelegramChat:
        return cls(id=int(payload["id"]), type=str(payload.get("type", "private")))


@dataclass(frozen=True, slots=True)
class TelegramMessage:
    message_id: int
    chat: TelegramChat
    from_user: TelegramUser | None
    text: str | None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> TelegramMessage:
        from_payload = payload.get("from")
        return cls(
            message_id=int(payload["message_id"]),
            chat=TelegramChat.from_api(payload["chat"]),
            from_user=TelegramUser.from_api(from_payload) if from_payload else None,
            text=payload.get("text"),
        )


@dataclass(frozen=True, slots=True)
class TelegramUpdate:
    update_id: int
    message: TelegramMessage | None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> TelegramUpdate:
        message_payload = payload.get("message")
        return cls(
            update_id=int(payload["update_id"]),
            message=TelegramMessage.from_api(message_payload) if message_payload else None,
        )
