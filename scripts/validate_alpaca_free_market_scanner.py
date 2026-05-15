from __future__ import annotations

import ast
import json
from pathlib import Path


REQUIRED_FILES = [
    "src/prediction_engine/scanners/alpaca_free_market_scanner.py",
    "scripts/run_alpaca_free_market_scanner.py",
    ".github/workflows/alpaca-free-market-scanner.yml",
]

OPTIONAL_OUTPUTS = [
    "state/prediction_engine/dynamic_alpaca_candidates.json",
    "docs/data/prediction_engine/alpaca_market_scanner_health.json",
]


def main() -> None:
    missing = [item for item in REQUIRED_FILES if not Path(item).exists()]
    if missing:
        raise SystemExit(f"Missing required files: {missing}")

    for item in REQUIRED_FILES:
        if item.endswith(".py"):
            ast.parse(Path(item).read_text(encoding="utf-8"))

    runtime_outputs = {}
    for item in OPTIONAL_OUTPUTS:
        path = Path(item)
        if not path.exists():
            runtime_outputs[item] = "not_generated_yet"
            continue
        json.loads(path.read_text(encoding="utf-8"))
        runtime_outputs[item] = "valid_json"

    print(json.dumps({
        "status": "PASS",
        "message": "Alpaca market scanner structural validation passed.",
        "runtime_outputs": runtime_outputs,
    }, indent=2))


if __name__ == "__main__":
    main()
