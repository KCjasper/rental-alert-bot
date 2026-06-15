from pathlib import Path

import pytest

from rental_alert_bot.config import ConfigurationError, Settings


def valid_environment() -> dict[str, str]:
    return {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "AUTHORIZED_TELEGRAM_USER_ID": "123456",
    }


def test_requires_bot_token() -> None:
    environment = valid_environment()
    environment["TELEGRAM_BOT_TOKEN"] = ""

    with pytest.raises(ConfigurationError, match="TELEGRAM_BOT_TOKEN is required"):
        Settings.from_environment(environment, require_secrets=True)


def test_requires_numeric_authorized_user_id() -> None:
    environment = valid_environment()
    environment["AUTHORIZED_TELEGRAM_USER_ID"] = "not-a-number"

    with pytest.raises(ConfigurationError, match="must be an integer"):
        Settings.from_environment(environment, require_secrets=True)


def test_loads_defaults() -> None:
    settings = Settings.from_environment(valid_environment(), require_secrets=True)

    assert settings.database_path == Path("data/rental_alert.db")
    assert settings.poll_interval_seconds == 300
    assert settings.poll_jitter_seconds == 30
    assert settings.timezone == "Asia/Taipei"


def test_rejects_invalid_poll_interval() -> None:
    environment = valid_environment()
    environment["POLL_INTERVAL_SECONDS"] = "0"

    with pytest.raises(ConfigurationError, match="greater than zero"):
        Settings.from_environment(environment, require_secrets=True)


def test_repr_redacts_credentials() -> None:
    settings = Settings.from_environment(valid_environment(), require_secrets=True)

    representation = repr(settings)

    assert "test-token" not in representation
    assert "123456" not in representation
    assert representation.count("<redacted>") == 2
