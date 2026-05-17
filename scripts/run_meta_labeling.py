from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    Path("docs/data/prediction_engine").mkdir(parents=True, exist_ok=True)
    Path("state/prediction_engine").mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [sys.executable, "-m", "prediction_engine.learning.meta_labeling"],
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
        "package": "Package 21 - ML Meta-Labeling Layer",
        "message": "Meta-labeling completed.",
        "outputs": [
            "docs/data/prediction_engine/meta_labeling_predictions.json",
            "docs/data/prediction_engine/meta_labeling_health.json",
            "state/prediction_engine/meta_labeling_predictions.json",
        ],
    }, indent=2))


if __name__ == "__main__":
    main()