from __future__ import annotations

import ast
import json
from pathlib import Path


REQUIRED = [
    "src/prediction_engine/runtime/__init__.py",
    "src/prediction_engine/runtime/runtime_worker.py",
    "scripts/run_runtime_worker.py",
    "scripts/runtime_loop.sh",
    "scripts/load_env.sh",
    "scripts/run_local_dashboard.sh",
    "scripts/push_dashboard_backup.sh",
    "scripts/install_oracle_vm_service.sh",
    ".github/workflows/runtime-worker-validation.yml",
    "README_PACKAGE_16.md",
]


def main() -> None:
    missing = [item for item in REQUIRED if not Path(item).exists()]

    python_failures = []
    for item in REQUIRED:
        if item.endswith(".py") and Path(item).exists():
            try:
                ast.parse(Path(item).read_text(encoding="utf-8"))
            except Exception as exc:
                python_failures.append({"file": item, "error": str(exc)})

    status = "PASS"
    if missing or python_failures:
        status = "FAIL"

    payload = {
        "status": status,
        "package": "Package 16 - Always-On Runtime Worker",
        "missing": missing,
        "python_failures": python_failures,
        "required": REQUIRED,
    }

    print(json.dumps(payload, indent=2))

    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
