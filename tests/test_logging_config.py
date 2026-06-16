import json
import logging

from rental_alert_bot.logging_config import JsonFormatter, configure_logging


def test_json_formatter_includes_event_and_extra_fields() -> None:
    record = logging.LogRecord(
        name="rental_alert_bot.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="startup_ok",
        args=(),
        exc_info=None,
    )
    record.subscription_id = 7

    payload = json.loads(JsonFormatter().format(record))

    assert payload["event"] == "startup_ok"
    assert payload["level"] == "INFO"
    assert payload["subscription_id"] == 7


def test_configure_logging_suppresses_http_client_info_logs() -> None:
    configure_logging("INFO")

    assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() == logging.WARNING
