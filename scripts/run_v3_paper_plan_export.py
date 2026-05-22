from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

PRE = DOCS / "v3_prebreakout_predictor.json"
REACTIVE = DOCS / "v3_research_alert_score.json"
REGIME = DOCS / "v3_market_regime_filter_health.json"
DAILY = DOCS / "v3_daily_research_report_health.json"
FINAL_AUDIT = DOCS / "final_repo_audit.json"

OUT_DOCS = DOCS / "v3_paper_order_plan.json"
OUT_HEALTH = DOCS / "v3_paper_order_plan_health.json"
OUT_STATE = STATE / "v3_paper_order_plan.json"

MAX_PLANS = 5
MAX_NOTIONAL_PER_PLAN = 2000.00


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
        if v is None or v == "":
            return default
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except Exception:
        return default


def rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    val = payload.get(key)
    return [r for r in val if isinstance(r, dict)] if isinstance(val, list) else []


def ticker(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def build_plan(row: dict[str, Any], layer: str) -> dict[str, Any] | None:
    sym = ticker(row)
    price = f(row.get("live_price") or row.get("price"))
    if not sym or price <= 0:
        return None

    if layer == "PRE_BREAKOUT":
        score = f(row.get("prebreakout_score_v3"))
        status = row.get("prebreakout_status_v3")
        confidence = row.get("prebreakout_confidence")
        note = row.get("prebreakout_note")
        target_price = f(row.get("prebreakout_target_price"))
        stop_price = f(row.get("prebreakout_stop_price"))
    else:
        score = f(row.get("research_alert_score_v3"))
        status = row.get("research_alert_status_v3")
        confidence = row.get("research_confidence")
        note = row.get("research_confidence_note")
        target_price = f(row.get("research_target_price"))
        stop_price = f(row.get("research_stop_price"))

    shares = int(MAX_NOTIONAL_PER_PLAN // price)
    if shares <= 0:
        return None

    return {
        "ticker": sym,
        "layer": layer,
        "status": status,
        "score": round(score, 4),
        "confidence": confidence,
        "note": note,
        "live_price": round(price, 4),
        "planned_shares": shares,
        "planned_notional": round(shares * price, 2),
        "target_price": round(target_price, 4),
        "stop_price": round(stop_price, 4),
        "day_move_pct": row.get("day_move_pct"),
        "relative_volume": row.get("relative_volume"),
        "vwap_distance_pct": row.get("vwap_distance_pct"),
        "spread_pct": row.get("spread_pct"),
        "quote_age_sec": row.get("quote_age_sec"),
        "order_type": "PLAN_ONLY_MARKET_WITH_BRACKET",
        "paper_order_allowed": False,
        "order_submission": False,
        "live_trading": False,
    }


def main() -> None:
    generated_at = now_iso()

    pre = read_json(PRE, {})
    reactive = read_json(REACTIVE, {})
    regime = read_json(REGIME, {})
    daily = read_json(DAILY, {})
    final_audit = read_json(FINAL_AUDIT, {})

    blockers: list[str] = []
    warnings: list[str] = []

    if final_audit.get("status") == "FAIL":
        blockers.append("final_repo_audit_not_passing")

    if daily.get("paper_trade_ready") is True:
        warnings.append("daily_report_says_paper_ready_but_export_remains_plan_only")

    if regime.get("regime") == "RISK_OFF":
        warnings.append("risk_off_regime_plan_review_only")

    candidate_plans: list[dict[str, Any]] = []

    for r in rows(pre, "candidates"):
        plan = build_plan(r, "PRE_BREAKOUT")
        if plan:
            candidate_plans.append(plan)

    for r in rows(reactive, "candidates"):
        plan = build_plan(r, "REACTIVE")
        if plan:
            candidate_plans.append(plan)

    candidate_plans.sort(key=lambda x: (x["layer"] == "PRE_BREAKOUT", x["score"]), reverse=True)

    # Remove duplicate tickers. Prefer first sorted plan.
    seen = set()
    unique_plans = []
    for p in candidate_plans:
        if p["ticker"] in seen:
            continue
        seen.add(p["ticker"])
        unique_plans.append(p)

    plans = unique_plans[:MAX_PLANS]

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "v3_paper_order_plan_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "plan_count": len(plans),
        "candidate_count_before_dedupe": len(candidate_plans),
        "market_regime": regime.get("regime"),
        "market_regime_score": regime.get("regime_score"),
        "max_notional_per_plan": MAX_NOTIONAL_PER_PLAN,
        "paper_order_allowed": False,
        "order_submission": False,
        "live_trading": False,
    }

    out = {
        "schema_version": "v3_paper_order_plan_v1",
        "generated_at": generated_at,
        "health": health,
        "plans": plans,
        "safety": {
            "purpose": "Review-only paper order plan. Does not submit orders.",
            "paper_order_allowed": False,
            "order_submission": False,
            "live_trading": False,
            "max_notional_per_plan": MAX_NOTIONAL_PER_PLAN,
        },
    }

    write_json(OUT_DOCS, out)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, out)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
