"""Small HTTP health server for cloud process checks."""

from __future__ import annotations

import json
import logging
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from rental_alert_bot.database import Database
from rental_alert_bot.schema import LATEST_SCHEMA_VERSION
from rental_alert_bot.schema_check import read_schema_version


class HealthServer:
    def __init__(
        self,
        *,
        database: Database,
        host: str = "0.0.0.0",
        port: int,
        path: str = "/health",
        logger: logging.Logger | None = None,
    ) -> None:
        if port < 0:
            raise ValueError("port must be zero or greater")
        if not path.startswith("/"):
            raise ValueError("path must start with /")
        self._database = database
        self._host = host
        self._port = port
        self._path = path
        self._logger = logger or logging.getLogger(__name__)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        if self._server is None:
            return self._port
        return int(self._server.server_port)

    def start(self) -> None:
        if self._server is not None:
            return

        handler = self._build_handler()
        self._server = ThreadingHTTPServer((self._host, self._port), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="rental-alert-health",
            daemon=True,
        )
        self._thread.start()
        self._logger.info(
            "health_server_started",
            extra={"host": self._host, "port": self.port, "path": self._path},
        )

    def stop(self) -> None:
        if self._server is None:
            return

        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        self._logger.info("health_server_stopped")

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        database = self._database
        health_path = self._path
        logger = self._logger

        class Handler(BaseHTTPRequestHandler):
            def do_HEAD(self) -> None:  # noqa: N802
                self._handle_health(include_body=False)

            def do_GET(self) -> None:  # noqa: N802
                self._handle_health(include_body=True)

            def log_message(self, format: str, *args: Any) -> None:
                logger.debug("health_server_request", extra={"message": format % args})

            def _handle_health(self, *, include_body: bool) -> None:
                if self.path.split("?", 1)[0] != health_path:
                    self.send_response(HTTPStatus.NOT_FOUND)
                    self.end_headers()
                    return

                status_code, payload = _check_health(database)
                body = json.dumps(payload, sort_keys=True).encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body) if include_body else 0))
                self.end_headers()
                if include_body:
                    self.wfile.write(body)

        return Handler


def _check_health(database: Database) -> tuple[HTTPStatus, dict[str, object]]:
    schema_version = read_schema_version(database.path)
    if schema_version is None:
        return (
            HTTPStatus.SERVICE_UNAVAILABLE,
            {
                "status": "unhealthy",
                "database": "missing",
                "required_schema_version": LATEST_SCHEMA_VERSION,
            },
        )
    if schema_version != LATEST_SCHEMA_VERSION:
        return (
            HTTPStatus.SERVICE_UNAVAILABLE,
            {
                "status": "unhealthy",
                "database": "schema_mismatch",
                "schema_version": schema_version,
                "required_schema_version": LATEST_SCHEMA_VERSION,
            },
        )

    try:
        database.check_integrity()
    except Exception as exc:
        return (
            HTTPStatus.SERVICE_UNAVAILABLE,
            {
                "status": "unhealthy",
                "database": "integrity_failed",
                "error": type(exc).__name__,
                "required_schema_version": LATEST_SCHEMA_VERSION,
            },
        )

    return (
        HTTPStatus.OK,
        {
            "status": "ok",
            "database": "ok",
            "schema_version": schema_version,
        },
    )
