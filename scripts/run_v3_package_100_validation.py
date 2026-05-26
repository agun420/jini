from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

CHECKS = {
    "enrichment": DOCS / "v3_enriched_rows_health.json",
    "market_regime": DOCS / "v3_market_regime_filter_health.json",
    "prebreakout": DOCS / "v3_prebreakout_predictor_health.json",
    "prebreakout_journal": DOCS / "v3_prebreakout_outcome_journal_health.json",
    "reactive": DOCS / "v3_research_alert_score_health.json",
    "reactive_journal": DOCS / "v3_research_alert_outcome_journal_health.json",
    "outcome_audit": DOCS / "v3_outcome_quality_audit_health.json",
    "daily_report": DOCS / "v3_daily_research_report_health.json",
    "regime_outcome_audit": DOCS / "v3_regime_outcome_audit_health.json",
    "math_edge": DOCS / "v3_mathematical_edge_model_health.json",
    "paper_plan": DOCS / "v3_paper_order_plan_health.json",
    "final_repo_audit": DOCS / "final_repo_audit.json",
}

DASHBOARD = Path("docs/index.html")

OUT_DOCS = DOCS / "v3_package_100_validation.json"
OUT_HEALTH = DOCS / "v3_package_100_validation_health.json"
OUT_STATE = STATE / "v3_package_100_validation.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return json.loads(raw) if raw else default
    except Exception as exc:
        return {"_read_error": str(exc), "_path": str(path)}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def status_of(payload: dict[str, Any]) -> str:
    return str(payload.get("status") or payload.get("score", {}).get("grade") or "UNKNOWN")


def is_false(payload: dict[str, Any], key: str) -> bool:
    return payload.get(key) is False


def main() -> None:
    generated_at = now_iso()

    blockers: list[str] = []
    warnings: list[str] = []
    results: dict[str, Any] = {}

    score = 100

    for name, path in CHECKS.items():
        payload = read_json(path, {})
        exists = path.exists()
        st = status_of(payload)

        results[name] = {
            "path": str(path),
            "exists": exists,
            "status": st,
            "generated_at": payload.get("generated_at"),
            "order_submission": payload.get("order_submission"),
            "live_trading": payload.get("live_trading"),
            "paper_order_allowed": payload.get("paper_order_allowed"),
            "blockers": payload.get("blockers") or payload.get("score", {}).get("blockers", []),
            "warnings": payload.get("warnings", []),
        }

        if not exists:
            blockers.append(f"missing_{name}")
            score -= 8
            continue

        if st == "FAIL":
            if name == "final_repo_audit":
                blockers.append("final_repo_audit_fail")
            else:
                blockers.append(f"{name}_fail")
            score -= 10

        if st == "WARN":
            warnings.append(f"{name}_warn")
            score -= 2

        # Hard safety checks.
        if payload.get("order_submission") is True:
            blockers.append(f"{name}_order_submission_true")
            score -= 20

        if payload.get("live_trading") is True:
            blockers.append(f"{name}_live_trading_true")
            score -= 30

        if payload.get("paper_order_allowed") is True:
            warnings.append(f"{name}_paper_order_allowed_true")
            score -= 5

    # Dashboard contract IDs.
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
        "edgeRows",
        "paperPlanRows",
    ]

    dashboard_text = DASHBOARD.read_text(encoding="utf-8") if DASHBOARD.exists() else ""
    missing_ids = [
        rid for rid in required_ids
        if f'id="{rid}"' not in dashboard_text and f"id='{rid}'" not in dashboard_text
    ]

    if missing_ids:
        blockers.append("dashboard_contract_missing_ids")
        score -= 10

    # Readiness logic.
    daily = read_json(CHECKS["daily_report"], {})
    paper_plan = read_json(CHECKS["paper_plan"], {})
    edge = read_json(CHECKS["math_edge"], {})
    final_repo = read_json(CHECKS["final_repo_audit"], {})

    pre_avg = daily.get("prebreakout_avg_return_pct")
    reactive_avg = daily.get("reactive_avg_return_pct")
    paper_trade_ready = daily.get("paper_trade_ready") is True

    if paper_trade_ready:
        warnings.append("daily_report_paper_trade_ready_true_but_package_100_keeps_submission_off")

    if final_repo.get("status") != "PASS":
        blockers.append("final_repo_not_pass")

    # Tomorrow readiness.
    tomorrow_readiness = "READY_FOR_RESEARCH_ONLY"
    if blockers:
        tomorrow_readiness = "NOT_READY_FIX_BLOCKERS"
    elif paper_plan.get("plan_count", 0) > 0 and edge.get("positive_edge_count", 0) > 0:
        tomorrow_readiness = "READY_FOR_RESEARCH_AND_PLAN_ONLY_REVIEW"

    score = max(0, min(100, score))
    grade = "PASS" if score >= 90 and not blockers else "FAIL"

    health = {
        "schema_version": "v3_package_100_validation_health_v1",
        "generated_at": generated_at,
        "status": grade,
        "score": score,
        "blockers": blockers,
        "warnings": warnings,
        "tomorrow_readiness": tomorrow_readiness,
        "missing_dashboard_ids": missing_ids,
        "prebreakout_avg_return_pct": pre_avg,
        "reactive_avg_return_pct": reactive_avg,
        "math_positive_edge_count": edge.get("positive_edge_count"),
        "paper_plan_count": paper_plan.get("plan_count"),
        "paper_trade_ready": False,
        "order_submission": False,
        "live_trading": False,
    }

    out = {
        "schema_version": "v3_package_100_validation_v1",
        "generated_at": generated_at,
        "health": health,
        "checks": results,
        "dashboard_contract": {
            "path": str(DASHBOARD),
            "missing_ids": missing_ids,
            "status": "PASS" if not missing_ids else "FAIL",
        },
        "recommendation": {
            "safe_to_run_tomorrow": not blockers,
            "safe_to_enable_paper_submission": False,
            "safe_to_enable_live_trading": False,
            "next_step": (
                "Run tomorrow in research-only and paper-plan-only mode. "
                "Review edge model and paper plan before any paper submission."
            ),
        },
        "safety": {
            "research_only": True,
            "paper_plan_only": True,
            "paper_order_submission": False,
            "live_trading": False,
            "not_financial_advice": True,
        },
    }

    write_json(OUT_DOCS, out)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, out)

    print(json.dumps(health, indent=2))

    if grade != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
