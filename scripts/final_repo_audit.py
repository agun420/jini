from __future__ import annotations

import ast
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple


AUDIT_DOCS_PATH = Path("docs/data/prediction_engine/final_repo_audit.json")
AUDIT_STATE_PATH = Path("state/prediction_engine/final_repo_audit.json")


CORE_FILES = {
    "Package 1A": [
        "src/prediction_engine/scanners/free_signal_schema.py",
        "src/prediction_engine/scanners/free_scanner_normalizer.py",
        "src/prediction_engine/dashboard/export_free_scanner_dashboard.py",
        "scripts/run_free_scanner_normalizer.py",
        ".github/workflows/free-scanner-normalizer.yml",
    ],
    "Package 1B": [
        "src/prediction_engine/scanners/alpaca_free_market_scanner.py",
        "scripts/run_alpaca_free_market_scanner.py",
        "scripts/validate_alpaca_free_market_scanner.py",
        ".github/workflows/alpaca-free-market-scanner.yml",
    ],
    "Package 8 Dashboard": [
        "docs/index.html",
        "docs/assets/styles.css",
        "docs/assets/app.js",
        "scripts/validate_dashboard_v2_package.py",
    ],
    "Package 2": [
        "src/prediction_engine/catalysts/sec_catalyst_scanner.py",
        "src/prediction_engine/catalysts/enrich_signal_dashboard_with_sec.py",
        "scripts/run_sec_catalyst_scanner.py",
        ".github/workflows/sec-catalyst-scanner.yml",
    ],
    "Package 3": [
        "src/prediction_engine/short_pressure/finra_short_volume_scanner.py",
        "src/prediction_engine/short_pressure/enrich_signal_dashboard_with_finra.py",
        "scripts/run_finra_short_pressure_scanner.py",
        ".github/workflows/finra-short-pressure-scanner.yml",
    ],
    "Package 4": [
        "src/prediction_engine/learning/signal_journal.py",
        "scripts/run_signal_journal.py",
        ".github/workflows/signal-journal.yml",
    ],
    "Package 5": [
        "src/prediction_engine/learning/outcome_labeler.py",
        "scripts/run_outcome_labeler.py",
        ".github/workflows/outcome-labeler.yml",
    ],
    "Package 6": [
        "src/prediction_engine/learning/adaptive_guard.py",
        "scripts/run_adaptive_guard.py",
        ".github/workflows/adaptive-guard.yml",
    ],
    "Package 7": [
        "src/prediction_engine/trade_gate/paper_execution_gate.py",
        "scripts/run_paper_execution_gate.py",
        ".github/workflows/paper-execution-gate.yml",
    ],
    "Alpaca Paid Upgrade": [
        "src/prediction_engine/scanners/alpaca_paid_config.py",
        "src/prediction_engine/scanners/alpaca_paid_market_scanner.py",
        "src/prediction_engine/catalysts/alpaca_news_scanner.py",
        "src/prediction_engine/catalysts/enrich_signal_dashboard_with_alpaca_news.py",
        "scripts/run_alpaca_paid_market_scanner.py",
        "scripts/run_alpaca_news_scanner.py",
        ".github/workflows/master-paid-alpaca-pipeline.yml",
    ],
    "Package 12 Advanced Quality": [
        "src/prediction_engine/quality/advanced_signal_quality.py",
        "scripts/run_advanced_signal_quality.py",
        ".github/workflows/advanced-signal-quality.yml",
    ],
    "Packages 13-15 Market Risk": [
        "src/prediction_engine/risk/real_money_readiness_guard.py",
        "src/prediction_engine/risk/halt_luld_circuit_guard.py",
        "src/prediction_engine/execution/slippage_fill_tracker.py",
        "scripts/run_real_money_readiness_guard.py",
        "scripts/run_halt_luld_circuit_guard.py",
        "scripts/run_slippage_fill_tracker.py",
        ".github/workflows/market-rule-risk-update.yml",
    ],
    "Package 9": [
        "scripts/run_master_free_scanner_pipeline.py",
        ".github/workflows/master-free-scanner-pipeline.yml",
    ],
}

EXPECTED_OUTPUTS = [
    "docs/data/prediction_engine/free_scanner.json",
    "docs/data/prediction_engine/signal_dashboard.json",
    "docs/data/prediction_engine/scanner_health.json",
    "docs/data/prediction_engine/master_pipeline_health.json",
    "docs/data/prediction_engine/alpaca_market_scanner_health.json",
]

OPTIONAL_OUTPUTS = [
    "docs/data/prediction_engine/master_paid_pipeline_health.json",
    "docs/data/prediction_engine/slippage_fill_tracker.json",
    "docs/data/prediction_engine/real_money_readiness_guard.json",
    "docs/data/prediction_engine/halt_luld_circuit_guard.json",
    "docs/data/prediction_engine/advanced_signal_quality.json",
    "docs/data/prediction_engine/signal_dashboard_market_guard_enriched.json",
    "docs/data/prediction_engine/signal_dashboard_quality_enriched.json",
    "docs/data/prediction_engine/signal_dashboard_news_enriched.json",
    "docs/data/prediction_engine/alpaca_news.json",
    "docs/data/prediction_engine/alpaca_paid_market_candidates.json",
    "state/prediction_engine/dynamic_alpaca_candidates.json",
    "docs/data/prediction_engine/sec_catalysts.json",
    "docs/data/prediction_engine/finra_short_pressure.json",
    "docs/data/prediction_engine/learning.json",
    "docs/data/prediction_engine/outcomes.json",
    "docs/data/prediction_engine/adaptive_guard.json",
    "docs/data/prediction_engine/paper_order_plan.json",
]

FORBIDDEN_LIVE_ENDPOINTS = [
    "https://api.alpaca.markets",
    "api.alpaca.markets/v2/orders",
]

REQUIRED_SAFETY_TERMS = [
    "PAPER_ORDER_SUBMISSION_ENABLED: \"false\"",
    "paper-api.alpaca.markets",
]


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    try:
        raw = path.read_text(encoding="utf-8").strip()
        return json.loads(raw) if raw else default
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")


def check_files() -> Dict[str, Any]:
    package_results: Dict[str, Any] = {}
    all_missing: List[str] = []

    for package, paths in CORE_FILES.items():
        missing = [item for item in paths if not Path(item).exists()]
        present = [item for item in paths if Path(item).exists()]
        package_results[package] = {
            "present_count": len(present),
            "expected_count": len(paths),
            "missing": missing,
            "status": "PASS" if not missing else "WARN",
        }
        all_missing.extend(missing)

    return {
        "packages": package_results,
        "missing_files": all_missing,
        "status": "PASS" if not all_missing else "WARN",
    }


def check_python_syntax() -> Dict[str, Any]:
    failures: List[Dict[str, str]] = []
    checked: List[str] = []

    for path in Path(".").glob("**/*.py"):
        if any(part in {".git", ".venv", "venv", "__pycache__"} for part in path.parts):
            continue

        checked.append(str(path))

        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except Exception as exc:
            failures.append({"path": str(path), "error": str(exc)})

    return {
        "checked_count": len(checked),
        "failures": failures,
        "status": "PASS" if not failures else "FAIL",
    }


def check_json_outputs() -> Dict[str, Any]:
    """
    Fresh-install aware JSON check.

    Base dashboard seed files must be valid if present in the package.
    Pipeline health files are runtime outputs, so missing pipeline health is WARN,
    not FAIL. After the master pipeline runs, those files should exist and be valid.
    """
    base_required = [
        "docs/data/prediction_engine/free_scanner.json",
        "docs/data/prediction_engine/signal_dashboard.json",
        "docs/data/prediction_engine/scanner_health.json",
    ]
    pipeline_alternatives = [
        "docs/data/prediction_engine/master_pipeline_health.json",
        "docs/data/prediction_engine/master_paid_pipeline_health.json",
        "docs/data/prediction_engine/alpaca_market_scanner_health.json",
    ]

    required_missing = []
    required_invalid = []
    runtime_missing = []
    optional_present = []
    optional_invalid = []

    for item in base_required:
        path = Path(item)
        if not path.exists():
            required_missing.append(item)
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            required_invalid.append({"path": item, "error": str(exc)})

    pipeline_found = False
    for item in pipeline_alternatives:
        path = Path(item)
        if not path.exists():
            continue
        pipeline_found = True
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            required_invalid.append({"path": item, "error": str(exc)})

    if not pipeline_found:
        runtime_missing.append("one_of:" + ",".join(pipeline_alternatives))

    for item in OPTIONAL_OUTPUTS:
        path = Path(item)
        if not path.exists():
            continue
        optional_present.append(item)
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            optional_invalid.append({"path": item, "error": str(exc)})

    if required_missing or required_invalid or optional_invalid:
        status = "FAIL"
    elif runtime_missing:
        status = "WARN"
    else:
        status = "PASS"

    return {
        "required_missing": required_missing,
        "runtime_missing": runtime_missing,
        "required_invalid": required_invalid,
        "optional_present": optional_present,
        "optional_invalid": optional_invalid,
        "status": status,
    }


def check_workflow_safety() -> Dict[str, Any]:
    workflows = sorted(Path(".github/workflows").glob("*.yml")) + sorted(Path(".github/workflows").glob("*.yaml"))
    issues: List[Dict[str, str]] = []
    checked = []

    for path in workflows:
        text = read_text(path)
        checked.append(str(path))

        if any(term in text for term in FORBIDDEN_LIVE_ENDPOINTS):
            issues.append({
                "path": str(path),
                "issue": "workflow_mentions_live_alpaca_endpoint",
            })

        if "paper-execution-gate" in path.name or "master-free-scanner-pipeline" in path.name or "master-paid-alpaca-pipeline" in path.name:
            if "PAPER_ORDER_SUBMISSION_ENABLED: \"false\"" not in text:
                issues.append({
                    "path": str(path),
                    "issue": "paper_submission_not_explicitly_false",
                })

        if "pull --rebase" in text:
            issues.append({
                "path": str(path),
                "issue": "workflow_uses_git_pull_rebase_risk",
            })

    return {
        "checked_workflows": checked,
        "issues": issues,
        "status": "PASS" if not issues else "FAIL",
    }


def check_code_safety() -> Dict[str, Any]:
    issues: List[Dict[str, str]] = []
    checked: List[str] = []

    for path in Path("src").glob("**/*.py"):
        text = read_text(path)
        checked.append(str(path))

        for endpoint in FORBIDDEN_LIVE_ENDPOINTS:
            if endpoint in text:
                issues.append({
                    "path": str(path),
                    "issue": f"forbidden_live_endpoint:{endpoint}",
                })

        if re.search(r"\bmargin\b", text, re.IGNORECASE) and "paper_execution_gate.py" in str(path):
            issues.append({
                "path": str(path),
                "issue": "margin_term_found_review_needed",
            })

    return {
        "checked_files": checked,
        "issues": issues,
        "status": "PASS" if not issues else "FAIL",
    }


def check_dashboard_contract() -> Dict[str, Any]:
    html = read_text(Path("docs/index.html"))
    app = read_text(Path("docs/assets/app.js"))
    css = read_text(Path("docs/assets/styles.css"))

    required_ids = [
        "metric-total-signals",
        "metric-trade-eligible",
        "adaptive-guard-panel",
        "paper-plan-panel",
        "outcomes-panel",
        "signals-table",
        "health-panel",
        "quality-panel",
        "learning-panel",
    ]

    required_refs = [
        "signal_dashboard_finra_enriched.json",
        "signal_dashboard_enriched.json",
        "signal_dashboard.json",
        "adaptive_guard.json",
        "paper_order_plan.json",
        "outcomes.json",
        "learning.json",
    ]

    missing_ids = [item for item in required_ids if item not in html]
    missing_refs = [item for item in required_refs if item not in app]

    issues = []
    if not Path("docs/index.html").exists():
        issues.append("missing_docs_index_html")
    if not Path("docs/assets/app.js").exists():
        issues.append("missing_docs_assets_app_js")
    if not Path("docs/assets/styles.css").exists():
        issues.append("missing_docs_assets_styles_css")
    if ".card" not in css:
        issues.append("css_missing_card_class")

    return {
        "missing_ids": missing_ids,
        "missing_data_refs": missing_refs,
        "issues": issues,
        "status": "PASS" if not missing_ids and not missing_refs and not issues else "FAIL",
    }


def check_master_pipeline_health() -> Dict[str, Any]:
    paid = read_json(Path("docs/data/prediction_engine/master_paid_pipeline_health.json"), {})
    free = read_json(Path("docs/data/prediction_engine/master_pipeline_health.json"), {})

    payload = paid or free
    source = "master_paid_pipeline_health.json" if paid else "master_pipeline_health.json" if free else "none"

    if not payload:
        return {
            "status": "WARN",
            "reason": "master_pipeline_health_not_found_yet",
            "source": source,
        }

    return {
        "status": "PASS" if payload.get("status") == "PASS" else "WARN",
        "pipeline_status": payload.get("status"),
        "summary": payload.get("summary") or payload.get("layers"),
        "source": source,
    }


def check_workflow_overlap() -> Dict[str, Any]:
    workflows = sorted(Path(".github/workflows").glob("*.yml")) + sorted(Path(".github/workflows").glob("*.yaml"))
    issues: List[Dict[str, str]] = []
    scheduled_allowed = {"master-paid-alpaca-pipeline.yml", "final-repo-audit.yml"}
    for path in workflows:
        text = read_text(path)
        if "schedule:" in text and path.name not in scheduled_allowed:
            issues.append({
                "path": str(path),
                "issue": "individual_package_workflow_should_not_be_scheduled_when_master_pipeline_exists",
            })
    return {
        "issues": issues,
        "status": "PASS" if not issues else "FAIL",
    }


def build_score(checks: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    weights = {
        "files": 5,
        "python_syntax": 20,
        "json_outputs": 15,
        "workflow_safety": 20,
        "code_safety": 15,
        "dashboard_contract": 10,
        "master_pipeline_health": 5,
        "workflow_overlap": 10,
    }

    score = 0
    blockers = []
    warnings = []

    for key, weight in weights.items():
        status = checks.get(key, {}).get("status")
        if status == "PASS":
            score += weight
        elif status == "WARN":
            score += weight * 0.5
            warnings.append(key)
        else:
            blockers.append(key)

    return {
        "score": round(score, 2),
        "max_score": 100,
        "grade": (
            "PASS" if score >= 90 and not blockers
            else "PASS_WITH_WARNINGS" if score >= 75 and not blockers
            else "FAIL"
        ),
        "blockers": blockers,
        "warnings": warnings,
    }


def main() -> None:
    checks = {
        "files": check_files(),
        "python_syntax": check_python_syntax(),
        "json_outputs": check_json_outputs(),
        "workflow_safety": check_workflow_safety(),
        "code_safety": check_code_safety(),
        "dashboard_contract": check_dashboard_contract(),
        "master_pipeline_health": check_master_pipeline_health(),
        "workflow_overlap": check_workflow_overlap(),
    }

    score = build_score(checks)

    payload = {
        "schema_version": "final_repo_audit_v1",
        "generated_at": now_utc_iso(),
        "status": score["grade"],
        "score": score,
        "checks": checks,
        "recommendation": {
            "safe_to_run_master_pipeline": score["grade"] in {"PASS", "PASS_WITH_WARNINGS"},
            "safe_to_enable_paper_submission": False,
            "reason": "Keep PAPER_ORDER_SUBMISSION_ENABLED=false until multiple clean days of paper order plans are reviewed.",
            "next_step": "Run Master Free Scanner Pipeline, review dashboard, then review paper_order_plan.json outputs before enabling any paper submission.",
        },
        "safety": {
            "paper_only": True,
            "live_trading": False,
            "order_submission_default": False,
            "audit_only": True,
            "disclaimer": "Audit validates repo readiness only. Not financial advice.",
        },
    }

    write_json(AUDIT_DOCS_PATH, payload)
    write_json(AUDIT_STATE_PATH, payload)

    print(json.dumps({
        "status": payload["status"],
        "score": payload["score"],
        "docs_path": str(AUDIT_DOCS_PATH),
        "state_path": str(AUDIT_STATE_PATH),
    }, indent=2))

    if payload["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
