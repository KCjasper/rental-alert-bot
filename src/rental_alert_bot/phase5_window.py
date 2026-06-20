"""Phase 5 validation time-window helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Phase5Window:
    since: datetime
    created_at: datetime

    def to_json_data(self) -> dict[str, str]:
        return {
            "since": self.since.isoformat(timespec="microseconds"),
            "created_at": self.created_at.isoformat(timespec="microseconds"),
        }


def create_phase5_window(path: Path | str, *, now: datetime | None = None) -> Phase5Window:
    destination = Path(path)
    if destination.exists():
        raise FileExistsError(f"phase 5 window file already exists: {destination}")

    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("phase 5 window timestamps must include a timezone")

    window = Phase5Window(
        since=current.astimezone(UTC),
        created_at=current.astimezone(UTC),
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(window.to_json_data(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return window


def load_phase5_window(path: Path | str) -> Phase5Window:
    source = Path(path)
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("phase 5 window file must contain a JSON object")
    since = _required_datetime(data, "since")
    created_at = _required_datetime(data, "created_at")
    return Phase5Window(since=since, created_at=created_at)


def _required_datetime(data: dict[str, Any], key: str) -> datetime:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"phase 5 window file is missing {key}")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"phase 5 window {key} must include a timezone offset")
    return parsed
