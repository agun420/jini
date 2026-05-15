from __future__ import annotations

import ast
import json
from pathlib import Path


REQUIRED = [
    "src/prediction_engine/risk/real_money_readiness_guard.py",
    "src/prediction_engine/risk/halt_luld_circuit_guard.py",
    "src/prediction_engine/execution/slippage_fill_tracker.py",
    "scripts/run_real_money_readiness_guard.py",
    "scripts/run_halt_luld_circuit_guard.py",
    "scripts/run_slippage_fill_tracker.py",
    ".github/workflows/market-rule-risk-update.yml",
    "README_MARKET_RULE_RISK_UPDATE.md",
]


def main() -> None:
    missing = [item for item in REQUIRED if not Path(item).exists()]
    if missing:
        raise SystemExit(f"Missing required files: {missing}")
    for item in REQUIRED:
        if item.endswith(".py"):
            ast.parse(Path(item).read_text(encoding="utf-8"))
    print(json.dumps({"status": "PASS", "message": "Market rule/risk update validation passed."}, indent=2))


if __name__ == "__main__":
    main()
