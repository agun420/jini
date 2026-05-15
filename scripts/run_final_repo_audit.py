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
        "Run Final Repo Audit",
        [sys.executable, "scripts/final_repo_audit.py"],
    )

    print(
        json.dumps(
            {
                "status": "PASS",
                "package": "Package 10 - Final Validation + Repo Audit v1",
                "message": "Final repo audit completed.",
                "outputs": [
                    "docs/data/prediction_engine/final_repo_audit.json",
                    "state/prediction_engine/final_repo_audit.json",
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
