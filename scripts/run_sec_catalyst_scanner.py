from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def run_step(name: str, cmd: list[str], required: bool = True) -> None:
    print(f"\n=== {name} ===")
    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if required and result.returncode != 0:
        raise SystemExit(f"{name} failed with exit code {result.returncode}")


def main() -> None:
    Path("docs/data/prediction_engine").mkdir(parents=True, exist_ok=True)
    Path("state/prediction_engine").mkdir(parents=True, exist_ok=True)

    run_step("Run SEC Catalyst Scanner", [sys.executable, "-m", "prediction_engine.catalysts.sec_catalyst_scanner"])
    run_step("Enrich Dashboard JSON With SEC", [sys.executable, "-m", "prediction_engine.catalysts.enrich_signal_dashboard_with_sec"], required=False)

    print(json.dumps({
        "status": "PASS",
        "package": "Package 2 - SEC Catalyst Risk Layer v1",
        "message": "Completed. No orders submitted.",
        "outputs": [
            "docs/data/prediction_engine/sec_catalysts.json",
            "docs/data/prediction_engine/sec_catalyst_health.json",
            "docs/data/prediction_engine/signal_dashboard_enriched.json",
            "docs/data/prediction_engine/free_scanner_enriched.json",
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
