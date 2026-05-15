from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def run_step(name: str, cmd: list[str]) -> None:
    print(f"\n=== {name} ===")
    result = subprocess.run(cmd, text=True, capture_output=True)

    if result.stdout:
        print(result.stdout)

    if result.stderr:
        print(result.stderr, file=sys.stderr)

    if result.returncode != 0:
        raise SystemExit(f"{name} failed with exit code {result.returncode}")


def main() -> None:
    Path("state/prediction_engine").mkdir(parents=True, exist_ok=True)
    Path("docs/data/prediction_engine").mkdir(parents=True, exist_ok=True)

    run_step(
        "Run Adaptive Guard",
        [sys.executable, "-m", "prediction_engine.learning.adaptive_guard"],
    )

    print(
        json.dumps(
            {
                "status": "PASS",
                "package": "Package 6 - Adaptive Guard v1",
                "message": "Adaptive guard completed. No orders submitted. No code changed.",
                "outputs": [
                    "state/prediction_engine/adaptive_guard_state.json",
                    "docs/data/prediction_engine/adaptive_guard.json",
                    "docs/data/prediction_engine/adaptive_guard_health.json",
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
