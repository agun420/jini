from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def run(name: str, cmd: list[str]) -> None:
    print(f"\n=== {name} ===")
    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if result.returncode != 0:
        raise SystemExit(f"{name} failed with code {result.returncode}")


def main() -> None:
    Path("docs/data/prediction_engine").mkdir(parents=True, exist_ok=True)
    Path("state/prediction_engine").mkdir(parents=True, exist_ok=True)

    run("Run Advanced Signal Quality", [sys.executable, "-m", "prediction_engine.quality.advanced_signal_quality"])

    print(json.dumps({
        "status": "PASS",
        "package": "Package 12 - Advanced Signal Quality Engine",
        "message": "Advanced quality scoring completed. No orders submitted.",
        "outputs": [
            "docs/data/prediction_engine/signal_dashboard_quality_enriched.json",
            "docs/data/prediction_engine/advanced_signal_quality.json",
            "docs/data/prediction_engine/advanced_signal_quality_health.json",
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
