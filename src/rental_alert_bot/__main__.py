"""Command-line entry point for the rental alert bot."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence

from rental_alert_bot import __version__
from rental_alert_bot.config import ConfigurationError, Settings
from rental_alert_bot.logging_config import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rental-alert-bot")
    parser.add_argument("--check", action="store_true", help="validate startup configuration")
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        settings = Settings.from_environment(require_secrets=True)
    except ConfigurationError as exc:
        configure_logging("INFO")
        logging.getLogger(__name__).error(
            "startup_configuration_invalid",
            extra={"error": str(exc)},
        )
        return 2

    configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)

    if args.check:
        logger.info(
            "startup_configuration_valid",
            extra={
                "database_path": str(settings.database_path),
                "poll_interval_seconds": settings.poll_interval_seconds,
                "timezone": settings.timezone,
            },
        )
        return 0

    logger.info(
        "application_core_ready",
        extra={
            "message_detail": (
                "591 parsing and SQLite persistence are ready; "
                "Telegram services are not implemented yet."
            )
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
