from __future__ import annotations

import ast
import json
from pathlib import Path


REQUIRED_FILES = [
    "scripts/run_master_free_scanner_pipeline.py",
    ".github/workflows/master-free-scanner-pipeline.yml",
    "README_PACKAGE_9.md",
]


def validate_python(path: Path) -> None:
    ast.parse(path.read_text(encoding="utf-8"))


def main() -> None:
    missing = [item for item in REQUIRED_FILES if not Path(item).exists()]
    if missing:
        raise SystemExit(f"Missing required files: {missing}")

    validate_python(Path("scripts/run_master_free_scanner_pipeline.py"))

    workflow = Path(".github/workflows/master-free-scanner-pipeline.yml").read_text(encoding="utf-8")
    required_workflow_terms = [
        "workflow_dispatch",
        "run_master_free_scanner_pipeline.py",
        "PAPER_ORDER_SUBMISSION_ENABLED: \"false\"",
    ]

    missing_terms = [term for term in required_workflow_terms if term not in workflow]
    if missing_terms:
        raise SystemExit(f"Workflow missing expected terms: {missing_terms}")

    print(json.dumps({
        "status": "PASS",
        "message": "Package 9 validation passed. Free master workflow may be manual-only in paid elite builds.",
        "checked_files": REQUIRED_FILES,
    }, indent=2))


if __name__ == "__main__":
    main()
