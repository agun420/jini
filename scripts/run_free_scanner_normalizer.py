from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def run_step(name: str, cmd: list[str]) -> None:
    print(f"\n=== {name} ===")

    result = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
    )

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
        "Build Free Scanner Normalizer",
        [sys.executable, "-m", "prediction_engine.scanners.free_scanner_normalizer"],
    )

    run_step(
        "Export Free Scanner Dashboard JSON",
        [sys.executable, "-m", "prediction_engine.dashboard.export_free_scanner_dashboard"],
    )

    print(
        json.dumps(
            {
                "status": "PASS",
                "package": "Package 1A - Free Scanner Normalizer v1",
                "message": "Completed. No orders submitted.",
                "outputs": [
                    "docs/data/prediction_engine/free_scanner.json",
                    "docs/data/prediction_engine/signal_dashboard.json",
                    "docs/data/prediction_engine/scanner_health.json",
                    "docs/data/prediction_engine/social_sentiment.json",
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
