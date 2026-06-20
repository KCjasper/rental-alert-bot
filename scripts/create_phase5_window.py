"""Create a Phase 5 validation time-window file."""

from __future__ import annotations

import argparse
from pathlib import Path

from rental_alert_bot.phase5_window import create_phase5_window


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a local Phase 5 validation window JSON file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/phase5-window.json"),
        help="Destination JSON path. Existing files are never overwritten.",
    )
    args = parser.parse_args()

    window = create_phase5_window(args.output)
    print("PHASE5_WINDOW_CREATED")
    print(f"path={args.output}")
    print(f"since={window.since.isoformat(timespec='microseconds')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
