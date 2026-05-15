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
    Path("docs/data/prediction_engine").mkdir(parents=True, exist_ok=True)
    Path("state/prediction_engine").mkdir(parents=True, exist_ok=True)

    run_step(
        "Run FINRA Short-Pressure Scanner",
        [sys.executable, "-m", "prediction_engine.short_pressure.finra_short_volume_scanner"],
    )

    run_step(
        "Enrich Scanner Dashboard with FINRA Context",
        [sys.executable, "-m", "prediction_engine.short_pressure.enrich_signal_dashboard_with_finra"],
    )

    print(json.dumps({
        "status": "PASS",
        "package": "Package 3 - FINRA Short-Sale Volume Layer v1",
        "message": "Completed. Context only. No orders submitted.",
        "outputs": [
            "docs/data/prediction_engine/finra_short_pressure.json",
            "docs/data/prediction_engine/finra_short_pressure_health.json",
            "docs/data/prediction_engine/signal_dashboard_finra_enriched.json",
            "docs/data/prediction_engine/free_scanner_finra_enriched.json",
            "state/prediction_engine/finra_short_volume_cache.json",
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
