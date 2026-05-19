from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    Path("docs/data/prediction_engine").mkdir(parents=True, exist_ok=True)
    Path("state/prediction_engine").mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [sys.executable, "scripts/operator_signal_resolver.py"],
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
        "package": "Package 33 - Operator Signal Resolver",
        "message": "Operator signal resolver completed.",
        "outputs": [
            "docs/data/prediction_engine/signal_dashboard_operator.json",
            "docs/data/prediction_engine/operator_signal_resolver_health.json",
            "state/prediction_engine/operator_signal_resolver.json",
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
