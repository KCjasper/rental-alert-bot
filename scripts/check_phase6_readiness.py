"""Check whether Railway deployment configuration is ready for phase 6."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from rental_alert_bot.phase6_readiness import (
    check_phase6_repository_readiness,
    check_phase6_runtime_environment,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check phase 6 Railway deployment readiness.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root containing railway.json. Default: current directory.",
    )
    parser.add_argument(
        "--runtime-env",
        action="store_true",
        help="Also validate actual Railway runtime variables from the current environment.",
    )
    args = parser.parse_args()

    if args.runtime_env:
        result = check_phase6_runtime_environment(os.environ)
    else:
        result = check_phase6_repository_readiness(args.project_root)

    for line in result.lines(runtime_env=args.runtime_env):
        print(line)
    return 0 if result.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
