from __future__ import annotations

import ast
import json
from pathlib import Path


REQUIRED = [
    "src/prediction_engine/learning/meta_labeling.py",
    "scripts/run_meta_labeling.py",
    "scripts/validate_meta_labeling_package.py",
    "README_PACKAGE_21.md",
]


def main() -> None:
    missing = [item for item in REQUIRED if not Path(item).exists()]

    failures = []
    for item in REQUIRED:
        if item.endswith(".py") and Path(item).exists():
            try:
                ast.parse(Path(item).read_text(encoding="utf-8"))
            except Exception as exc:
                failures.append({"file": item, "error": str(exc)})

    status = "PASS" if not missing and not failures else "FAIL"

    print(json.dumps({
        "status": status,
        "package": "Package 21 - ML Meta-Labeling Layer",
        "missing": missing,
        "python_failures": failures,
    }, indent=2))

    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()