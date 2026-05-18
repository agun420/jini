from __future__ import annotations

import ast
import json
from pathlib import Path


REQUIRED = [
    "scripts/production_monitor.py",
    "scripts/run_production_monitor.py",
    "scripts/validate_production_monitor_package.py",
    "README_PACKAGE_24.md",
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

    status = "PASS" if not missing and not python_failures else "FAIL"

    print(json.dumps({
        "status": status,
        "package": "Package 24 - Production Monitor",
        "missing": missing,
        "python_failures": python_failures,
    }, indent=2))

    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
