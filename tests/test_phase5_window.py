import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rental_alert_bot.phase5_window import create_phase5_window, load_phase5_window

NOW = datetime(2026, 6, 21, 10, 0, tzinfo=UTC)


def test_creates_and_loads_phase5_window_file(tmp_path: Path) -> None:
    path = tmp_path / "phase5-window.json"

    created = create_phase5_window(path, now=NOW)
    loaded = load_phase5_window(path)

    assert created.since == NOW
    assert loaded.since == NOW
    assert loaded.created_at == NOW
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "since": "2026-06-21T10:00:00.000000+00:00",
        "created_at": "2026-06-21T10:00:00.000000+00:00",
    }


def test_phase5_window_file_is_not_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "phase5-window.json"
    create_phase5_window(path, now=NOW)

    with pytest.raises(FileExistsError, match="already exists"):
        create_phase5_window(path, now=NOW + timedelta(seconds=1))


def test_phase5_window_rejects_naive_timestamps(tmp_path: Path) -> None:
    path = tmp_path / "phase5-window.json"

    with pytest.raises(ValueError, match="timezone"):
        create_phase5_window(path, now=datetime(2026, 6, 21, 10, 0))


def test_phase5_window_rejects_invalid_files(tmp_path: Path) -> None:
    path = tmp_path / "phase5-window.json"
    path.write_text('{"since":"2026-06-21T10:00:00"}', encoding="utf-8")

    with pytest.raises(ValueError, match="timezone"):
        load_phase5_window(path)
