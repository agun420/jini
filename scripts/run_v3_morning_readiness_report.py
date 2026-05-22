from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

PACKAGE_100 = DOCS / "v3_package_100_validation_health.json"
REGIME = DOCS / "v3_market_regime_filter_health.json"
EDGE = DOCS / "v3_mathematical_edge_model.json"
EDGE_HEALTH = DOCS / "v3_mathematical_edge_model_health.json"
PAPER_PLAN = DOCS / "v3_paper_order_plan.json"
PAPER_PLAN_HEALTH = DOCS / "v3_paper_order_plan_health.json"
DAILY = DOCS / "v3_daily_research_report_health.json"
FINAL_AUDIT = DOCS / "final_repo_audit.json"

OUT_DOCS = DOCS / "v3_morning_readiness_report.json"
OUT_HEALTH = DOCS / "v3_morning_readiness_report_health.json"
OUT_STATE = STATE / "v3_morning_readiness_report.json"


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


def f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    val = payload.get(key)
    return [r for r in val if isinstance(r, dict)] if isinstance(val, list) else []


def slim_plan(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": p.get("ticker"),
        "layer": p.get("layer"),
        "edge_status": p.get("edge_status"),
        "edge_score": p.get("edge_score"),
        "expected_value_pct": p.get("expected_value_pct"),
        "estimated_win_probability": p.get("estimated_win_probability"),
        "risk_reward_ratio": p.get("risk_reward_ratio"),
        "live_price": p.get("live_price"),
        "planned_shares": p.get("planned_shares"),
        "planned_notional": p.get("planned_notional"),
        "target_price": p.get("target_price"),
        "stop_price": p.get("stop_price"),
        "order_submission": p.get("order_submission"),
        "live_trading": p.get("live_trading"),
    }


def main() -> None:
    generated_at = now_iso()

    package_100 = read_json(PACKAGE_100, {})
    regime = read_json(REGIME, {})
    edge = read_json(EDGE, {})
    edge_health = read_json(EDGE_HEALTH, {})
    paper_plan = read_json(PAPER_PLAN, {})
    paper_plan_health = read_json(PAPER_PLAN_HEALTH, {})
    daily = read_json(DAILY, {})
    final_audit = read_json(FINAL_AUDIT, {})

    blockers: list[str] = []
    warnings: list[str] = []

    if package_100.get("status") != "PASS":
        blockers.append("package_100_not_passing")

    if final_audit.get("status") == "FAIL":
        blockers.append("final_repo_audit_not_passing")

    if paper_plan_health.get("order_submission") is not False:
        blockers.append("paper_plan_order_submission_not_false")

    if paper_plan_health.get("live_trading") is not False:
        blockers.append("paper_plan_live_trading_not_false")

    if edge_health.get("order_submission") is not False:
        blockers.append("edge_model_order_submission_not_false")

    if edge_health.get("live_trading") is not False:
        blockers.append("edge_model_live_trading_not_false")

    if regime.get("regime") == "RISK_OFF":
        warnings.append("market_regime_risk_off_review_only")

    if f(edge_health.get("positive_edge_count")) <= 0:
        warnings.append("no_positive_edge_candidates_currently")

    if f(paper_plan_health.get("plan_count")) <= 0:
        warnings.append("no_paper_plan_candidates_currently")

    plans = [slim_plan(p) for p in rows(paper_plan, "plans")]

    # Lock the current watchlist for review only.
    locked_watchlist = plans[:5]

    readiness = "READY_FOR_RESEARCH_ONLY"
    if blockers:
        readiness = "NOT_READY_FIX_BLOCKERS"
    elif plans:
        readiness = "READY_FOR_RESEARCH_AND_PLAN_ONLY_REVIEW"

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "v3_morning_readiness_report_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "readiness": readiness,
        "package_100_status": package_100.get("status"),
        "package_100_score": package_100.get("score"),
        "market_regime": regime.get("regime"),
        "market_regime_score": regime.get("regime_score"),
        "positive_edge_count": edge_health.get("positive_edge_count"),
        "paper_plan_count": paper_plan_health.get("plan_count"),
        "locked_watchlist_count": len(locked_watchlist),
        "winning_layer": daily.get("winning_layer"),
        "promotion_decision": daily.get("promotion_decision"),
        "paper_trade_ready": False,
        "paper_order_allowed": False,
        "order_submission": False,
        "live_trading": False,
    }

    out = {
        "schema_version": "v3_morning_readiness_report_v1",
        "generated_at": generated_at,
        "health": health,
        "locked_watchlist": locked_watchlist,
        "inputs": {
            "package_100": package_100,
            "market_regime": regime,
            "edge_health": edge_health,
            "paper_plan_health": paper_plan_health,
            "daily_report": daily,
            "final_audit_status": final_audit.get("status"),
        },
        "instructions": {
            "morning_rule": "Review locked_watchlist manually. Do not enable paper order submission.",
            "if_risk_off": "Treat plans as watch-only and require stronger confirmation.",
            "if_no_plans": "Do nothing. Let scanner collect data.",
        },
        "safety": {
            "research_only": True,
            "paper_plan_only": True,
            "paper_trade_ready": False,
            "paper_order_allowed": False,
            "order_submission": False,
            "live_trading": False,
        },
    }

    write_json(OUT_DOCS, out)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, out)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
