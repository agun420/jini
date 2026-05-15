from __future__ import annotations

import ast
import json
import runpy
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


def syntax_check() -> None:
    failures = []
    for path in Path(".").glob("**/*.py"):
        if any(part in {".git", ".venv", "venv", "__pycache__"} for part in path.parts):
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except Exception as exc:
            failures.append({"path": str(path), "error": str(exc)})

    if failures:
        raise SystemExit(json.dumps({"syntax_failures": failures}, indent=2))

    print("Python syntax check passed.")


def run_validator(path: str) -> None:
    script = Path(path)
    if not script.exists():
        print(f"Skipping missing validator: {path}")
        return

    print(f"\n=== {path} ===")
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:
        code = exc.code
        if code not in (None, 0):
            raise


def run_smoke_tests_without_pytest() -> None:
    print("\n=== smoke tests ===")
    import importlib.util

    test_path = Path("tests/test_free_scanner_smoke.py")
    if not test_path.exists():
        print("No smoke test file found.")
        return

    spec = importlib.util.spec_from_file_location("test_free_scanner_smoke", test_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    count = 0
    for name in dir(module):
        if name.startswith("test_"):
            func = getattr(module, name)
            if callable(func):
                func()
                count += 1

    print(f"Smoke tests passed: {count}")


def main() -> None:
    syntax_check()

    for script in VALIDATION_SCRIPTS:
        run_validator(script)

    run_smoke_tests_without_pytest()

    print(json.dumps({
        "status": "PASS",
        "message": "Full validation suite completed.",
        "validators": VALIDATION_SCRIPTS,
    }, indent=2))


if __name__ == "__main__":
    main()
