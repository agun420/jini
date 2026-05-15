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
        "Run Outcome Labeler",
        [sys.executable, "-m", "prediction_engine.learning.outcome_labeler"],
    )

    print(
        json.dumps(
            {
                "status": "PASS",
                "package": "Package 5 - Outcome Labeling v1",
                "message": "Outcome labeling completed. No orders submitted. No thresholds changed.",
                "outputs": [
                    "state/prediction_engine/outcome_labels.json",
                    "docs/data/prediction_engine/outcomes.json",
                    "docs/data/prediction_engine/outcome_labeler_health.json",
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
