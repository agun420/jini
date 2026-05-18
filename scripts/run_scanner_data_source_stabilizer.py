from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    Path("docs/data/prediction_engine").mkdir(parents=True, exist_ok=True)
    Path("state/prediction_engine").mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [sys.executable, "scripts/scanner_data_source_stabilizer.py"],
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
        "package": "Package 29 - Scanner Data Source Stabilizer",
        "message": "Scanner data source stabilizer completed.",
        "outputs": [
            "docs/data/prediction_engine/signal_dashboard_stable.json",
            "docs/data/prediction_engine/scanner_data_source_health.json",
            "state/prediction_engine/last_good_signal_rows.json",
            "state/prediction_engine/scanner_data_source_health.json",
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
