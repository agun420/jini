from __future__ import annotations

import ast
import json
from pathlib import Path


REQUIRED_RUNTIME_FILES = [
    "scripts/run_master_free_scanner_pipeline.py",
]

RECOMMENDED_WORKFLOWS = [
    ".github/workflows/master-paid-alpaca-pipeline.yml",
    ".github/workflows/master-free-scanner-pipeline.yml",
]

OPTIONAL_PACKAGE_FILES = [
    "README_PACKAGE_9.md",
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

    workflow_present = [
        item for item in RECOMMENDED_WORKFLOWS
        if Path(item).exists()
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

    workflow_checks = []
    for workflow in workflow_present:
        text = Path(workflow).read_text(encoding="utf-8")
        workflow_checks.append({
            "path": workflow,
            "has_workflow_dispatch": "workflow_dispatch" in text,
            "has_python_run_step": "python" in text,
            "paper_submission_false": 'PAPER_ORDER_SUBMISSION_ENABLED: "false"' in text or "PAPER_ORDER_SUBMISSION_ENABLED" not in text,
            "has_git_pull_rebase": "git pull --rebase" in text,
        })

    workflow_hard_failures = [
        item for item in workflow_checks
        if not item["has_workflow_dispatch"] or item["has_git_pull_rebase"]
    ]

    payload = {
        "status": (
            "PASS"
            if not missing_required
            and not syntax_failures
            and workflow_present
            and not workflow_hard_failures
            else "FAIL"
        ),
        "package": "Package 9 - Master Pipeline",
        "required_runtime_files": REQUIRED_RUNTIME_FILES,
        "recommended_workflows": RECOMMENDED_WORKFLOWS,
        "workflow_present": workflow_present,
        "optional_package_files": OPTIONAL_PACKAGE_FILES,
        "missing_required": missing_required,
        "missing_optional_warning_only": missing_optional,
        "python_checks": python_checks,
        "workflow_checks": workflow_checks,
        "workflow_hard_failures": workflow_hard_failures,
        "note": (
            "The paid build may use master-paid-alpaca-pipeline.yml as the main pipeline. "
            "README files are warnings only."
        ),
    }

    print(json.dumps(payload, indent=2))

    if payload["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
