"""Phase 6 Railway deployment readiness checks."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from rental_alert_bot.config import ConfigurationError, Settings

EXPECTED_START_COMMAND = "uv run --frozen python scripts/run_local_service.py"
EXPECTED_HEALTHCHECK_PATH = "/health"
EXPECTED_RESTART_POLICY = "ALWAYS"
EXPECTED_DATABASE_PREFIX = "/app/data/"
REQUIRED_ENV_KEYS = (
    "TELEGRAM_BOT_TOKEN",
    "AUTHORIZED_TELEGRAM_USER_ID",
    "DATABASE_PATH",
    "POLL_INTERVAL_SECONDS",
    "POLL_JITTER_SECONDS",
    "REQUEST_TIMEOUT_SECONDS",
    "INITIAL_NOTIFICATION_BATCH_SIZE",
    "TELEGRAM_SEND_DELAY_SECONDS",
    "FAILURE_ALERT_THRESHOLD",
    "LOG_LEVEL",
    "TZ",
    "PORT",
    "HEALTHCHECK_PATH",
)


@dataclass(frozen=True, slots=True)
class Phase6ReadinessResult:
    failures: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return not self.failures

    def lines(self, *, runtime_env: bool = False) -> tuple[str, ...]:
        status = (
            "PHASE6_RUNTIME_ENV_OK"
            if runtime_env and self.ready
            else "PHASE6_RUNTIME_ENV_NOT_READY"
            if runtime_env
            else "PHASE6_REPOSITORY_READY"
            if self.ready
            else "PHASE6_REPOSITORY_NOT_READY"
        )
        return (
            (status,)
            + tuple(f"failure={failure}" for failure in self.failures)
            + tuple(f"warning={warning}" for warning in self.warnings)
        )


def check_phase6_repository_readiness(project_root: Path | str) -> Phase6ReadinessResult:
    root = Path(project_root)
    failures: list[str] = []

    railway_config_path = root / "railway.json"
    if not railway_config_path.exists():
        failures.append("railway.json is missing")
    else:
        try:
            railway_config = json.loads(railway_config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failures.append(f"railway.json is invalid JSON: {exc.msg}")
        else:
            deploy_config = railway_config.get("deploy", {})
            if deploy_config.get("startCommand") != EXPECTED_START_COMMAND:
                failures.append("railway.json deploy.startCommand is not the local service entry")
            if deploy_config.get("healthcheckPath") != EXPECTED_HEALTHCHECK_PATH:
                failures.append("railway.json deploy.healthcheckPath must be /health")
            if deploy_config.get("restartPolicyType") != EXPECTED_RESTART_POLICY:
                failures.append("railway.json deploy.restartPolicyType must be ALWAYS")

    example_path = root / ".env.example"
    if not example_path.exists():
        failures.append(".env.example is missing")
    else:
        keys = _read_env_keys(example_path)
        missing_keys = [key for key in REQUIRED_ENV_KEYS if key not in keys]
        if missing_keys:
            failures.append(".env.example missing keys: " + ", ".join(missing_keys))

    if not (root / "docs" / "railway-deployment.html").exists():
        failures.append("docs/railway-deployment.html is missing")

    return Phase6ReadinessResult(failures=tuple(failures))


def check_phase6_runtime_environment(
    environment: Mapping[str, str],
    *,
    database_prefix: str = EXPECTED_DATABASE_PREFIX,
) -> Phase6ReadinessResult:
    failures: list[str] = []
    try:
        settings = Settings.from_environment(
            environment,
            require_secrets=True,
            dotenv_path=None,
        )
    except ConfigurationError as exc:
        return Phase6ReadinessResult(failures=(str(exc),))

    if settings.health_port is None:
        failures.append("PORT is required so Railway can reach the healthcheck endpoint")
    if settings.health_path != EXPECTED_HEALTHCHECK_PATH:
        failures.append("HEALTHCHECK_PATH must match railway.json healthcheckPath: /health")

    database_path = str(settings.database_path).replace("\\", "/")
    if not database_path.startswith(database_prefix):
        failures.append(f"DATABASE_PATH must be under the Railway volume path {database_prefix}")

    return Phase6ReadinessResult(failures=tuple(failures))


def _read_env_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _value = line.split("=", 1)
        keys.add(key.strip())
    return keys
