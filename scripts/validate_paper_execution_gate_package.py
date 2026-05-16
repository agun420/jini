from __future__ import annotations

import ast
import json
from pathlib import Path


REQUIRED_RUNTIME_FILES = [
    "src/prediction_engine/trade_gate/paper_execution_gate.py",
    "scripts/run_paper_execution_gate.py",
]

OPTIONAL_PACKAGE_FILES = [
    ".github/workflows/paper-execution-gate.yml",
    "README_PACKAGE_7.md",
]


def validate_python(path: Path) -> dict:
    try:
        ast.parse(path.read_text(encoding="utf-8"))
        return {"path": str(path), "status": "PASS"}
    except Exception as exc:
        return {"path": str(path), "status": "FAIL", "error": str(exc)}


def main() -> None:
    missing_required = [
        item for item in REQUIRED_RUNTIME_FILES
        if not Path(item).exists()
    ]

    missing_optional = [
        item for item in OPTIONAL_PACKAGE_FILES
        if not Path(item).exists()
    ]

    python_checks = []
    for item in REQUIRED_RUNTIME_FILES:
        path = Path(item)
        if path.exists() and path.suffix == ".py":
            python_checks.append(validate_python(path))

    syntax_failures = [
        item for item in python_checks
        if item.get("status") != "PASS"
    ]

    payload = {
        "status": "PASS" if not missing_required and not syntax_failures else "FAIL",
        "package": "Package 7 - Paper Execution Gate",
        "required_runtime_files": REQUIRED_RUNTIME_FILES,
        "optional_package_files": OPTIONAL_PACKAGE_FILES,
        "missing_required": missing_required,
        "missing_optional_warning_only": missing_optional,
        "python_checks": python_checks,
        "note": (
            "Optional workflow/readme files are warnings only. "
            "Runtime validation requires the paper execution gate module and runner script."
        ),
    }

    print(json.dumps(payload, indent=2))

    if payload["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
