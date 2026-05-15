from __future__ import annotations

import ast
import json
from pathlib import Path


REQUIRED_FILES = [
    "scripts/final_repo_audit.py",
    "scripts/run_final_repo_audit.py",
    "scripts/validate_final_audit_package.py",
    ".github/workflows/final-repo-audit.yml",
    "README_PACKAGE_10.md",
]


def validate_python(path: Path) -> None:
    ast.parse(path.read_text(encoding="utf-8"))


def main() -> None:
    missing = [item for item in REQUIRED_FILES if not Path(item).exists()]
    if missing:
        raise SystemExit(f"Missing required files: {missing}")

    for item in [
        "scripts/final_repo_audit.py",
        "scripts/run_final_repo_audit.py",
        "scripts/validate_final_audit_package.py",
    ]:
        validate_python(Path(item))

    workflow = Path(".github/workflows/final-repo-audit.yml").read_text(encoding="utf-8")
    for term in ["workflow_dispatch", "final_repo_audit.py", "contents: write"]:
        if term not in workflow:
            raise SystemExit(f"Workflow missing expected term: {term}")

    print(
        json.dumps(
            {
                "status": "PASS",
                "message": "Package 10 validation passed.",
                "checked_files": REQUIRED_FILES,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
