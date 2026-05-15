from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def run_step(name: str, cmd: list[str], required: bool = True) -> bool:
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
        message = f"{name} failed with exit code {result.returncode}"
        if required:
            raise SystemExit(message)
        print(message)
        return False

    return True


def module_exists(module_name: str) -> bool:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        text=True,
        capture_output=True,
    )
    return result.returncode == 0


def main() -> None:
    Path("docs/data/prediction_engine").mkdir(parents=True, exist_ok=True)
    Path("state/prediction_engine").mkdir(parents=True, exist_ok=True)

    run_step(
        "Build Alpaca Free Market Candidates",
        [sys.executable, "-m", "prediction_engine.scanners.alpaca_free_market_scanner"],
        required=True,
    )

    # If Package 1A is installed, run it immediately so dashboard JSON refreshes too.
    if module_exists("prediction_engine.scanners.free_scanner_normalizer"):
        run_step(
            "Run Package 1A Normalizer",
            [sys.executable, "-m", "prediction_engine.scanners.free_scanner_normalizer"],
            required=True,
        )

        if module_exists("prediction_engine.dashboard.export_free_scanner_dashboard"):
            run_step(
                "Export Free Scanner Dashboard JSON",
                [sys.executable, "-m", "prediction_engine.dashboard.export_free_scanner_dashboard"],
                required=True,
            )
    else:
        print("Package 1A normalizer not found. Candidate file was still generated.")

    print(
        json.dumps(
            {
                "status": "PASS",
                "package": "Package 1B - Alpaca Free Market Scanner v1",
                "message": "Completed. No orders submitted.",
                "outputs": [
                    "state/prediction_engine/dynamic_alpaca_candidates.json",
                    "docs/data/prediction_engine/alpaca_market_scanner_health.json",
                    "docs/data/prediction_engine/free_scanner.json if Package 1A exists",
                    "docs/data/prediction_engine/signal_dashboard.json if Package 1A exists",
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
