from __future__ import annotations

import ast
import json
from pathlib import Path


REQUIRED = [
    "src/prediction_engine/quality/__init__.py",
    "src/prediction_engine/quality/advanced_signal_quality.py",
    "scripts/run_advanced_signal_quality.py",
    ".github/workflows/advanced-signal-quality.yml",
    "README_PACKAGE_12.md",
]


def main() -> None:
    missing = [item for item in REQUIRED if not Path(item).exists()]
    if missing:
        raise SystemExit(f"Missing files: {missing}")
    for item in REQUIRED:
        if item.endswith(".py"):
            ast.parse(Path(item).read_text(encoding="utf-8"))
    print(json.dumps({
        "status": "PASS",
        "message": "Package 12 validation passed.",
        "checked_files": REQUIRED,
    }, indent=2))


if __name__ == "__main__":
    main()
