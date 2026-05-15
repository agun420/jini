from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


PIPELINE_HEALTH_PATH = Path("docs/data/prediction_engine/master_pipeline_health.json")
PIPELINE_STATE_PATH = Path("state/prediction_engine/master_pipeline_state.json")


STEPS = [
    {
        "name": "Package 1B - Alpaca Free Market Scanner",
        "script": "scripts/run_alpaca_free_market_scanner.py",
        "required": False,
        "description": "Pulls Alpaca IEX market data and writes dynamic candidates.",
    },
    {
        "name": "Package 1A - Free Scanner Normalizer",
        "script": "scripts/run_free_scanner_normalizer.py",
        "required": True,
        "description": "Normalizes candidate data and writes signal_dashboard.json.",
    },
    {
        "name": "Package 2 - SEC Catalyst Scanner",
        "script": "scripts/run_sec_catalyst_scanner.py",
        "required": False,
        "description": "Adds SEC catalyst and risk context.",
    },
    {
        "name": "Package 3 - FINRA Short-Pressure Scanner",
        "script": "scripts/run_finra_short_pressure_scanner.py",
        "required": False,
        "description": "Adds FINRA short-sale pressure context.",
    },
    {
        "name": "Package 4 - Signal Journal",
        "script": "scripts/run_signal_journal.py",
        "required": False,
        "description": "Saves every current signal into signal history.",
    },
    {
        "name": "Package 5 - Outcome Labeler",
        "script": "scripts/run_outcome_labeler.py",
        "required": False,
        "description": "Labels 30/60/90 minute outcomes from signal history.",
    },
    {
        "name": "Package 6 - Adaptive Guard",
        "script": "scripts/run_adaptive_guard.py",
        "required": False,
        "description": "Creates risk mode and adaptive thresholds.",
    },
    {
        "name": "Package 7 - Paper Execution Gate",
        "script": "scripts/run_paper_execution_gate.py",
        "required": False,
        "description": "Creates a paper order plan only by default.",
    },
    {
        "name": "Package 8 - Dashboard v2 Validator",
        "script": "scripts/validate_dashboard_v2_package.py",
        "required": False,
        "description": "Validates dashboard files are present.",
    },
]


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")


def run_script(step: Dict[str, Any]) -> Dict[str, Any]:
    script = Path(step["script"])

    result: Dict[str, Any] = {
        "name": step["name"],
        "script": str(script),
        "required": bool(step.get("required")),
        "description": step.get("description"),
        "started_at": now_utc_iso(),
        "finished_at": None,
        "status": "PENDING",
        "return_code": None,
        "stdout_tail": "",
        "stderr_tail": "",
    }

    if not script.exists():
        result["finished_at"] = now_utc_iso()
        result["status"] = "SKIPPED_MISSING_SCRIPT" if not step.get("required") else "FAILED_MISSING_REQUIRED_SCRIPT"
        result["return_code"] = None
        return result

    completed = subprocess.run(
        [sys.executable, str(script)],
        text=True,
        capture_output=True,
        env=os.environ.copy(),
    )

    result["finished_at"] = now_utc_iso()
    result["return_code"] = completed.returncode
    result["stdout_tail"] = (completed.stdout or "")[-4000:]
    result["stderr_tail"] = (completed.stderr or "")[-4000:]

    if completed.returncode == 0:
        result["status"] = "PASS"
    else:
        result["status"] = "FAILED"

    print(f"\n=== {step['name']} ===")
    print(f"Status: {result['status']}")
    if completed.stdout:
        print(completed.stdout)
    if completed.stderr:
        print(completed.stderr, file=sys.stderr)

    return result


def validate_required_outputs() -> Dict[str, Any]:
    required_outputs = [
        "docs/data/prediction_engine/free_scanner.json",
        "docs/data/prediction_engine/signal_dashboard.json",
        "docs/data/prediction_engine/scanner_health.json",
    ]

    optional_outputs = [
        "state/prediction_engine/dynamic_alpaca_candidates.json",
        "docs/data/prediction_engine/sec_catalysts.json",
        "docs/data/prediction_engine/finra_short_pressure.json",
        "docs/data/prediction_engine/learning.json",
        "docs/data/prediction_engine/outcomes.json",
        "docs/data/prediction_engine/adaptive_guard.json",
        "docs/data/prediction_engine/paper_order_plan.json",
    ]

    missing_required = [item for item in required_outputs if not Path(item).exists()]
    present_optional = [item for item in optional_outputs if Path(item).exists()]
    missing_optional = [item for item in optional_outputs if not Path(item).exists()]

    return {
        "required_outputs": required_outputs,
        "missing_required_outputs": missing_required,
        "present_optional_outputs": present_optional,
        "missing_optional_outputs": missing_optional,
        "required_outputs_ok": not missing_required,
    }


def build_summary(step_results: List[Dict[str, Any]], output_validation: Dict[str, Any]) -> Dict[str, Any]:
    failed_required = [
        item for item in step_results
        if item["required"] and item["status"] not in {"PASS"}
    ]

    failed_optional = [
        item for item in step_results
        if not item["required"] and item["status"] == "FAILED"
    ]

    skipped_optional = [
        item for item in step_results
        if not item["required"] and item["status"] == "SKIPPED_MISSING_SCRIPT"
    ]

    pipeline_pass = (
        not failed_required
        and output_validation.get("required_outputs_ok", False)
    )

    return {
        "pipeline_pass": pipeline_pass,
        "required_failed_count": len(failed_required),
        "optional_failed_count": len(failed_optional),
        "optional_skipped_count": len(skipped_optional),
        "steps_total": len(step_results),
        "steps_passed": sum(1 for item in step_results if item["status"] == "PASS"),
        "steps_skipped": len(skipped_optional),
        "required_outputs_ok": output_validation.get("required_outputs_ok", False),
    }


def main() -> None:
    Path("docs/data/prediction_engine").mkdir(parents=True, exist_ok=True)
    Path("state/prediction_engine").mkdir(parents=True, exist_ok=True)

    started_at = now_utc_iso()
    step_results: List[Dict[str, Any]] = []

    for step in STEPS:
        result = run_script(step)
        step_results.append(result)

        if result["required"] and result["status"] != "PASS":
            print(f"Required step failed: {result['name']}", file=sys.stderr)
            break

    output_validation = validate_required_outputs()
    summary = build_summary(step_results, output_validation)

    payload = {
        "schema_version": "master_pipeline_health_v1",
        "generated_at": now_utc_iso(),
        "started_at": started_at,
        "finished_at": now_utc_iso(),
        "status": "PASS" if summary["pipeline_pass"] else "FAILED",
        "mode": "paper_only_research",
        "summary": summary,
        "steps": step_results,
        "output_validation": output_validation,
        "safety": {
            "paper_only": True,
            "live_trading": False,
            "order_submission_default": False,
            "workflow_orchestrator_only": True,
            "disclaimer": "Master pipeline orchestrates research outputs only. Not financial advice.",
        },
    }

    write_json(PIPELINE_HEALTH_PATH, payload)
    write_json(PIPELINE_STATE_PATH, payload)

    print(json.dumps({
        "status": payload["status"],
        "summary": summary,
        "health_path": str(PIPELINE_HEALTH_PATH),
        "state_path": str(PIPELINE_STATE_PATH),
    }, indent=2))

    if not summary["pipeline_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
