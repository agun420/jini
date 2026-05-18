from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    Path("docs/data/prediction_engine").mkdir(parents=True, exist_ok=True)
    Path("state/prediction_engine").mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [sys.executable, "scripts/auth_failure_safe_mode.py"],
        text=True,
        capture_output=True,
    )

    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    if result.returncode != 0:
        raise SystemExit(result.returncode)

    print(json.dumps({
        "status": "PASS",
        "package": "Package 31 - Auth-Failure Safe Mode",
        "message": "Auth-failure safe mode completed.",
        "outputs": [
            "docs/data/prediction_engine/signal_dashboard_safe_mode.json",
            "docs/data/prediction_engine/auth_failure_safe_mode_health.json",
            "state/prediction_engine/auth_failure_safe_mode.json",
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
