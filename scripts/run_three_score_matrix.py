from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    Path("docs/data/prediction_engine").mkdir(parents=True, exist_ok=True)
    Path("state/prediction_engine").mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [sys.executable, "-m", "prediction_engine.scoring.three_score_matrix"],
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
        "package": "Package 17 - Three-Score Matrix",
        "message": "Three-score matrix completed.",
        "outputs": [
            "docs/data/prediction_engine/signal_dashboard_scored.json",
            "docs/data/prediction_engine/three_score_matrix.json",
            "docs/data/prediction_engine/three_score_matrix_health.json",
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
