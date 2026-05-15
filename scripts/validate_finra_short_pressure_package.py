from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "src/prediction_engine/short_pressure/__init__.py",
    "src/prediction_engine/short_pressure/finra_short_volume_scanner.py",
    "src/prediction_engine/short_pressure/enrich_signal_dashboard_with_finra.py",
    "scripts/run_finra_short_pressure_scanner.py",
]


def main() -> None:
    missing = []
    for item in REQUIRED:
        path = ROOT / item
        if not path.exists():
            missing.append(item)
            continue
        if path.suffix == ".py":
            ast.parse(path.read_text(encoding="utf-8"))

    if missing:
        raise SystemExit(f"Missing required files: {missing}")

    print(json.dumps({"status": "PASS", "validated_files": REQUIRED}, indent=2))


if __name__ == "__main__":
    main()
