from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    Path("docs/data/prediction_engine").mkdir(parents=True, exist_ok=True)
    Path("state/prediction_engine").mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [sys.executable, "-m", "prediction_engine.features.volume_profile"],
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
        "package": "Package 19 - Time-Slot RVOL + Volume Profile",
        "message": "Time-slot RVOL completed.",
        "outputs": [
            "docs/data/prediction_engine/time_slot_rvol.json",
            "docs/data/prediction_engine/signal_dashboard_rvol_enriched.json",
            "docs/data/prediction_engine/time_slot_rvol_health.json",
        ],
    }, indent=2))


if __name__ == "__main__":
    main()