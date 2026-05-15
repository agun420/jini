from __future__ import annotations

import ast
import json
from pathlib import Path


REQUIRED_FILES = [
    "src/prediction_engine/learning/adaptive_guard.py",
    "scripts/run_adaptive_guard.py",
    ".github/workflows/adaptive-guard.yml",
    "README_PACKAGE_6.md",
]


def validate_python(path: Path) -> None:
    ast.parse(path.read_text(encoding="utf-8"))


def main() -> None:
    missing = [item for item in REQUIRED_FILES if not Path(item).exists()]
    if missing:
        raise SystemExit(f"Missing required files: {missing}")

    validate_python(Path("src/prediction_engine/learning/adaptive_guard.py"))
    validate_python(Path("scripts/run_adaptive_guard.py"))

    print(
        json.dumps(
            {
                "status": "PASS",
                "message": "Package 6 validation passed.",
                "checked_files": REQUIRED_FILES,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
