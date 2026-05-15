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
    Path("state/prediction_engine").mkdir(parents=True, exist_ok=True)
    Path("docs/data/prediction_engine").mkdir(parents=True, exist_ok=True)

    run_step(
        "Run Paper Execution Gate",
        [sys.executable, "-m", "prediction_engine.trade_gate.paper_execution_gate"],
    )

    print(
        json.dumps(
            {
                "status": "PASS",
                "package": "Package 7 - Paper Execution Gate v1",
                "message": "Paper execution gate completed.",
                "safety": "Order submission is disabled by default unless PAPER_ORDER_SUBMISSION_ENABLED=true.",
                "outputs": [
                    "state/prediction_engine/paper_order_plan.json",
                    "docs/data/prediction_engine/paper_order_plan.json",
                    "docs/data/prediction_engine/paper_execution_gate_health.json",
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
