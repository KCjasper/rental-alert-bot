"""Environment-backed application settings."""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    """Raised when required application configuration is invalid."""


def _required_value(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "").strip()
    if not value:
        raise ConfigurationError(f"{name} is required")
    return value


def _strip_optional_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_dotenv_file(path: Path | str = ".env") -> dict[str, str]:
    dotenv_path = Path(path)
    if not dotenv_path.exists():
        return {}

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(dotenv_path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        if "=" not in line:
            raise ConfigurationError(f"{dotenv_path}:{line_number} must use KEY=VALUE")

        name, raw_value = line.split("=", 1)
        name = name.strip()
        if not name:
            raise ConfigurationError(f"{dotenv_path}:{line_number} contains an empty key")
        values[name] = _strip_optional_quotes(raw_value.strip())
    return values


def _merged_environment(
    environment: Mapping[str, str] | None,
    dotenv_path: Path | str | None,
) -> Mapping[str, str]:
    if environment is not None:
        return environment

    merged: MutableMapping[str, str] = {}
    if dotenv_path is not None:
        merged.update(load_dotenv_file(dotenv_path))
    merged.update(os.environ)
    return merged


def _positive_integer(
    environment: Mapping[str, str],
    name: str,
    default: int,
    *,
    allow_zero: bool = False,
) -> int:
    raw_value = environment.get(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc

    minimum = 0 if allow_zero else 1
    if value < minimum:
        comparison = "zero or greater" if allow_zero else "greater than zero"
        raise ConfigurationError(f"{name} must be {comparison}")
    return value


def _positive_float(environment: Mapping[str, str], name: str, default: float) -> float:
    raw_value = environment.get(name, str(default)).strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number") from exc

    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_bot_token: str
    authorized_telegram_user_id: int
    database_path: Path
    poll_interval_seconds: int
    poll_jitter_seconds: int
    request_timeout_seconds: int
    initial_notification_batch_size: int
    telegram_send_delay_seconds: float
    failure_alert_threshold: int
    log_level: str
    timezone: str

    def __repr__(self) -> str:
        return (
            "Settings("
            "telegram_bot_token=<redacted>, "
            "authorized_telegram_user_id=<redacted>, "
            f"database_path={self.database_path!r}, "
            f"poll_interval_seconds={self.poll_interval_seconds!r}, "
            f"poll_jitter_seconds={self.poll_jitter_seconds!r}, "
            f"request_timeout_seconds={self.request_timeout_seconds!r}, "
            f"initial_notification_batch_size={self.initial_notification_batch_size!r}, "
            f"telegram_send_delay_seconds={self.telegram_send_delay_seconds!r}, "
            f"failure_alert_threshold={self.failure_alert_threshold!r}, "
            f"log_level={self.log_level!r}, "
            f"timezone={self.timezone!r}"
            ")"
        )

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        require_secrets: bool,
        dotenv_path: Path | str | None = ".env",
    ) -> Settings:
        values = _merged_environment(environment, dotenv_path)

        token = _required_value(values, "TELEGRAM_BOT_TOKEN") if require_secrets else ""
        user_id_raw = (
            _required_value(values, "AUTHORIZED_TELEGRAM_USER_ID")
            if require_secrets
            else values.get("AUTHORIZED_TELEGRAM_USER_ID", "1")
        )

        try:
            user_id = int(user_id_raw)
        except ValueError as exc:
            raise ConfigurationError("AUTHORIZED_TELEGRAM_USER_ID must be an integer") from exc
        if user_id <= 0:
            raise ConfigurationError("AUTHORIZED_TELEGRAM_USER_ID must be greater than zero")

        log_level = values.get("LOG_LEVEL", "INFO").strip().upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigurationError("LOG_LEVEL is invalid")

        timezone = values.get("TZ", "Asia/Taipei").strip()
        if not timezone:
            raise ConfigurationError("TZ is required")

        database_path = Path(values.get("DATABASE_PATH", "./data/rental_alert.db")).expanduser()

        return cls(
            telegram_bot_token=token,
            authorized_telegram_user_id=user_id,
            database_path=database_path,
            poll_interval_seconds=_positive_integer(values, "POLL_INTERVAL_SECONDS", 300),
            poll_jitter_seconds=_positive_integer(
                values,
                "POLL_JITTER_SECONDS",
                30,
                allow_zero=True,
            ),
            request_timeout_seconds=_positive_integer(values, "REQUEST_TIMEOUT_SECONDS", 20),
            initial_notification_batch_size=_positive_integer(
                values,
                "INITIAL_NOTIFICATION_BATCH_SIZE",
                10,
            ),
            telegram_send_delay_seconds=_positive_float(
                values,
                "TELEGRAM_SEND_DELAY_SECONDS",
                1.2,
            ),
            failure_alert_threshold=_positive_integer(
                values,
                "FAILURE_ALERT_THRESHOLD",
                3,
            ),
            log_level=log_level,
            timezone=timezone,
        )
