import json
import urllib.error
import urllib.request
from pathlib import Path

from rental_alert_bot.database import Database
from rental_alert_bot.health_server import HealthServer


def test_health_server_reports_ok_for_current_database(tmp_path: Path) -> None:
    database = Database(tmp_path / "rental.db")
    database.initialize()
    server = HealthServer(database=database, host="127.0.0.1", port=0, path="/health")

    try:
        server.start()
        url = f"http://127.0.0.1:{server.port}/health"
        with urllib.request.urlopen(url, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.stop()

    assert response.status == 200
    assert payload["status"] == "ok"
    assert payload["database"] == "ok"


def test_health_server_rejects_wrong_path(tmp_path: Path) -> None:
    database = Database(tmp_path / "rental.db")
    database.initialize()
    server = HealthServer(database=database, host="127.0.0.1", port=0, path="/health")

    try:
        server.start()
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{server.port}/wrong", timeout=5)
        except urllib.error.HTTPError as exc:
            status = exc.code
    finally:
        server.stop()

    assert status == 404


def test_health_server_reports_unhealthy_for_missing_database(tmp_path: Path) -> None:
    database = Database(tmp_path / "missing.db")
    server = HealthServer(database=database, host="127.0.0.1", port=0, path="/health")

    try:
        server.start()
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{server.port}/health", timeout=5)
        except urllib.error.HTTPError as exc:
            status = exc.code
            payload = json.loads(exc.read().decode("utf-8"))
    finally:
        server.stop()

    assert status == 503
    assert payload["status"] == "unhealthy"
    assert payload["database"] == "missing"
