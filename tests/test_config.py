from pathlib import Path

import pytest

from rental_alert_bot.config import ConfigurationError, Settings, load_dotenv_file


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


def test_loads_settings_from_dotenv_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    token_key = "TELEGRAM_BOT_TOKEN"
    user_id_key = "AUTHORIZED_TELEGRAM_USER_ID"
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "\n".join(
            [
                f"{token_key}='test-token'",
                f'{user_id_key}="123456"',
                "DATABASE_PATH=./data/from-dotenv.db",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("AUTHORIZED_TELEGRAM_USER_ID", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)

    settings = Settings.from_environment(require_secrets=True, dotenv_path=dotenv_path)

    assert settings.telegram_bot_token == "test-token"
    assert settings.authorized_telegram_user_id == 123456
    assert settings.database_path == Path("data/from-dotenv.db")


def test_environment_values_override_dotenv_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_key = "TELEGRAM_BOT_TOKEN"
    user_id_key = "AUTHORIZED_TELEGRAM_USER_ID"
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "\n".join(
            [
                f"{token_key}=dotenv-token",
                f"{user_id_key}=111111",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "environment-token")
    monkeypatch.setenv("AUTHORIZED_TELEGRAM_USER_ID", "222222")

    settings = Settings.from_environment(require_secrets=True, dotenv_path=dotenv_path)

    assert settings.telegram_bot_token == "environment-token"
    assert settings.authorized_telegram_user_id == 222222


def test_load_dotenv_file_rejects_invalid_lines(tmp_path: Path) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("TELEGRAM_BOT_TOKEN\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="KEY=VALUE"):
        load_dotenv_file(dotenv_path)


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
