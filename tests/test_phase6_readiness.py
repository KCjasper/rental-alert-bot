from pathlib import Path

from rental_alert_bot.phase6_readiness import (
    check_phase6_repository_readiness,
    check_phase6_runtime_environment,
)


def test_phase6_repository_readiness_passes_for_project_root() -> None:
    project_root = Path(__file__).resolve().parents[1]

    result = check_phase6_repository_readiness(project_root)

    assert result.ready is True
    assert result.lines()[0] == "PHASE6_REPOSITORY_READY"


def test_phase6_runtime_environment_requires_railway_volume_path() -> None:
    environment = {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "AUTHORIZED_TELEGRAM_USER_ID": "123456",
        "DATABASE_PATH": "./data/rental_alert.db",
        "PORT": "8080",
        "HEALTHCHECK_PATH": "/health",
    }

    result = check_phase6_runtime_environment(environment)

    assert result.ready is False
    assert any("DATABASE_PATH" in failure for failure in result.failures)


def test_phase6_runtime_environment_passes_with_required_variables() -> None:
    environment = {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "AUTHORIZED_TELEGRAM_USER_ID": "123456",
        "DATABASE_PATH": "/app/data/rental_alert.db",
        "PORT": "8080",
        "HEALTHCHECK_PATH": "/health",
    }

    result = check_phase6_runtime_environment(environment)

    assert result.ready is True
    assert result.lines(runtime_env=True)[0] == "PHASE6_RUNTIME_ENV_OK"
