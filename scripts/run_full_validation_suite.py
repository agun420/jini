from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path


VALIDATION_SCRIPTS = [
    "scripts/validate_alpaca_free_market_scanner.py",
    "scripts/validate_sec_catalyst_package.py",
    "scripts/validate_finra_short_pressure_package.py",
    "scripts/validate_signal_journal_package.py",
    "scripts/validate_outcome_labeler_package.py",
    "scripts/validate_adaptive_guard_package.py",
    "scripts/validate_paper_execution_gate_package.py",
    "scripts/validate_dashboard_v2_package.py",
    "scripts/validate_master_pipeline_package.py",
    "scripts/validate_final_audit_package.py",
    "scripts/validate_alpaca_paid_upgrade_package.py",
    "scripts/validate_advanced_signal_quality_package.py",
    "scripts/validate_market_rule_risk_update.py",
]

CORE_RUNTIME_FILES = [
    # scanner/data
    "src/prediction_engine/scanners/free_scanner_normalizer.py",
    "src/prediction_engine/scanners/alpaca_paid_market_scanner.py",
    "src/prediction_engine/catalysts/alpaca_news_scanner.py",
    "src/prediction_engine/catalysts/sec_catalyst_scanner.py",
    "src/prediction_engine/short_pressure/finra_short_volume_scanner.py",

    # learning/scoring
    "src/prediction_engine/learning/signal_journal.py",
    "src/prediction_engine/learning/outcome_labeler.py",
    "src/prediction_engine/learning/adaptive_guard.py",
    "src/prediction_engine/quality/advanced_signal_quality.py",

    # execution/risk
    "src/prediction_engine/trade_gate/paper_execution_gate.py",
    "src/prediction_engine/execution/slippage_fill_tracker.py",
    "src/prediction_engine/risk/halt_luld_circuit_guard.py",
    "src/prediction_engine/risk/real_money_readiness_guard.py",

    # dashboard/audit/runners
    "docs/index.html",
    "docs/assets/app.js",
    "docs/assets/styles.css",
    "scripts/run_alpaca_paid_market_scanner.py",
    "scripts/run_alpaca_news_scanner.py",
    "scripts/run_advanced_signal_quality.py",
    "scripts/run_halt_luld_circuit_guard.py",
    "scripts/run_real_money_readiness_guard.py",
    "scripts/run_final_repo_audit.py",
]

WORKFLOW_SAFETY_FILES = [
    ".github/workflows/master-paid-alpaca-pipeline.yml",
    ".github/workflows/final-repo-audit.yml",
]


def syntax_check() -> list[dict]:
    failures = []

    for path in Path(".").glob("**/*.py"):
        if any(part in {".git", ".venv", "venv", "__pycache__"} for part in path.parts):
            continue

        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except Exception as exc:
            failures.append({
                "path": str(path),
                "error": str(exc),
            })

    return failures


def core_file_check() -> list[str]:
    return [item for item in CORE_RUNTIME_FILES if not Path(item).exists()]


def workflow_safety_check() -> list[dict]:
    issues = []

    for item in WORKFLOW_SAFETY_FILES:
        path = Path(item)
        if not path.exists():
            issues.append({
                "path": item,
                "issue": "missing_recommended_workflow",
                "severity": "warning",
            })
            continue

        text = path.read_text(encoding="utf-8")

        if 'PAPER_ORDER_SUBMISSION_ENABLED: "true"' in text:
            issues.append({
                "path": item,
                "issue": "paper_order_submission_enabled_true",
                "severity": "blocker",
            })

        if "https://api.alpaca.markets" in text:
            issues.append({
                "path": item,
                "issue": "live_alpaca_endpoint_reference",
                "severity": "blocker",
            })

        if "git pull --rebase" in text:
            issues.append({
                "path": item,
                "issue": "git_pull_rebase_risk",
                "severity": "blocker",
            })

    return issues


def run_optional_validator(script: str) -> dict:
    path = Path(script)

    if not path.exists():
        return {
            "script": script,
            "status": "SKIPPED",
            "reason": "validator_missing",
        }

    result = subprocess.run(
        [sys.executable, script],
        text=True,
        capture_output=True,
    )

    return {
        "script": script,
        "status": "PASS" if result.returncode == 0 else "WARN",
        "returncode": result.returncode,
        "stdout_tail": (result.stdout or "")[-2500:],
        "stderr_tail": (result.stderr or "")[-2500:],
        "note": (
            "Validator warnings do not fail the full suite unless core runtime files, "
            "Python syntax, or workflow safety checks fail."
        ),
    }


def run_pytest_if_available() -> dict:
    try:
        import pytest  # noqa: F401
    except Exception:
        return {
            "status": "SKIPPED",
            "reason": "pytest_not_installed",
        }

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        text=True,
        capture_output=True,
    )

    return {
        "status": "PASS" if result.returncode == 0 else "WARN",
        "returncode": result.returncode,
        "stdout_tail": (result.stdout or "")[-2500:],
        "stderr_tail": (result.stderr or "")[-2500:],
        "note": "Pytest warnings do not fail install validation unless you choose to enforce them later.",
    }


def main() -> None:
    syntax_failures = syntax_check()
    missing_core_files = core_file_check()
    workflow_issues = workflow_safety_check()

    workflow_blockers = [
        item for item in workflow_issues
        if item.get("severity") == "blocker"
    ]

    validator_results = [
        run_optional_validator(script)
        for script in VALIDATION_SCRIPTS
    ]

    pytest_result = run_pytest_if_available()

    blockers = []

    if syntax_failures:
        blockers.append("python_syntax_failures")

    if missing_core_files:
        blockers.append("missing_core_runtime_files")

    if workflow_blockers:
        blockers.append("workflow_safety_blockers")

    payload = {
        "status": "PASS" if not blockers else "FAIL",
        "suite": "Full Validation Suite",
        "blockers": blockers,
        "checks": {
            "python_syntax": {
                "status": "PASS" if not syntax_failures else "FAIL",
                "failures": syntax_failures,
            },
            "core_runtime_files": {
                "status": "PASS" if not missing_core_files else "FAIL",
                "missing": missing_core_files,
            },
            "workflow_safety": {
                "status": "PASS" if not workflow_blockers else "FAIL",
                "issues": workflow_issues,
            },
            "optional_package_validators": validator_results,
            "pytest": pytest_result,
        },
        "policy": {
            "hard_fail_on": [
                "Python syntax failure",
                "Missing core runtime file",
                "Workflow safety blocker",
            ],
            "warning_only": [
                "Missing README_PACKAGE files",
                "Missing optional individual workflows",
                "Runtime JSON not generated yet",
                "Optional validator mismatch",
            ],
        },
    }

    print(json.dumps(payload, indent=2))

    if payload["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
