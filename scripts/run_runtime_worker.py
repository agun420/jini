from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    Path("docs/data/prediction_engine").mkdir(parents=True, exist_ok=True)
    Path("state/prediction_engine").mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [sys.executable, "-m", "prediction_engine.runtime.runtime_worker"],
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
        "package": "Package 16 - Always-On Runtime Worker",
        "message": "Runtime worker completed one loop.",
        "outputs": [
            "docs/data/prediction_engine/runtime_heartbeat.json",
            "docs/data/prediction_engine/runtime_status.json",
            "state/prediction_engine/runtime_status.json",
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
