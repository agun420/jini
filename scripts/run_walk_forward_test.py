from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    Path("docs/data/prediction_engine").mkdir(parents=True, exist_ok=True)
    Path("state/prediction_engine").mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [sys.executable, "-m", "prediction_engine.learning.walk_forward"],
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
        "package": "Package 20 - Slippage-Aware Walk-Forward Testing",
        "message": "Walk-forward test completed.",
        "outputs": [
            "docs/data/prediction_engine/walk_forward_results.json",
            "docs/data/prediction_engine/walk_forward_health.json",
            "state/prediction_engine/walk_forward_results.json",
        ],
    }, indent=2))


if __name__ == "__main__":
    main()