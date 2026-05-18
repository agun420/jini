from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    Path("docs/data/prediction_engine").mkdir(parents=True, exist_ok=True)
    Path("state/prediction_engine").mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [sys.executable, "scripts/data_feed_truth_guard.py"],
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
        "package": "Package 28 - Data Feed Truth Check + Zero Price Guard",
        "message": "Data feed truth guard completed.",
        "outputs": [
            "docs/data/prediction_engine/signal_dashboard_data_guard_enriched.json",
            "docs/data/prediction_engine/data_feed_quality_health.json",
            "state/prediction_engine/data_feed_quality.json",
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
