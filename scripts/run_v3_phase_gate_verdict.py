from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

ENRICH_HEALTH = DOCS / "v3_enriched_rows_health.json"
REGIME_HEALTH = DOCS / "v3_market_regime_filter_health.json"
PRE = DOCS / "v3_prebreakout_predictor.json"
PRE_HEALTH = DOCS / "v3_prebreakout_predictor_health.json"
REACTIVE = DOCS / "v3_research_alert_score.json"
REACTIVE_HEALTH = DOCS / "v3_research_alert_score_health.json"
EDGE = DOCS / "v3_mathematical_edge_model.json"
EDGE_HEALTH = DOCS / "v3_mathematical_edge_model_health.json"
PAPER_PLAN = DOCS / "v3_paper_order_plan.json"
PAPER_PLAN_HEALTH = DOCS / "v3_paper_order_plan_health.json"
SAFETY = DOCS / "v3_hard_safety_lock_health.json"
PACKAGE_100 = DOCS / "v3_package_100_validation_health.json"
MORNING = DOCS / "v3_morning_readiness_report_health.json"

OUT_DOCS = DOCS / "v3_phase_gate_verdict.json"
OUT_HEALTH = DOCS / "v3_phase_gate_verdict_health.json"
OUT_STATE = STATE / "v3_phase_gate_verdict.json"


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


def rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    return [r for r in value if isinstance(r, dict)] if isinstance(value, list) else []


def f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def ticker(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def index_by_ticker(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in items:
        sym = ticker(r)
        if sym and sym not in out:
            out[sym] = r
    return out


def status_passish(status: Any) -> bool:
    return str(status or "").upper() in {"PASS", "WARN"}


def make_gate(status: str, reason: str, value: Any = None) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "value": value,
    }


def build_verdict(
    sym: str,
    pre_row: dict[str, Any] | None,
    reactive_row: dict[str, Any] | None,
    edge_row: dict[str, Any] | None,
    plan_row: dict[str, Any] | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    enrich_h = context["enrich_h"]
    regime_h = context["regime_h"]
    safety_h = context["safety_h"]

    gates: dict[str, Any] = {}

    # Gate 1: safety
    safety_pass = (
        safety_h.get("status") == "PASS"
        and safety_h.get("safe_for_research") is True
        and safety_h.get("order_submission") is False
        and safety_h.get("live_trading") is False
    )
    gates["safety_lock"] = make_gate(
        "PASS" if safety_pass else "FAIL",
        "Hard safety lock passed. Orders and live trading are off." if safety_pass else "Hard safety lock failed or not fresh.",
        {
            "safe_for_research": safety_h.get("safe_for_research"),
            "safe_for_paper_submission": safety_h.get("safe_for_paper_submission"),
            "safe_for_live_trading": safety_h.get("safe_for_live_trading"),
            "order_submission": safety_h.get("order_submission"),
            "live_trading": safety_h.get("live_trading"),
        },
    )

    # Gate 2: data quality
    data_pass = enrich_h.get("status") == "PASS"
    gates["data_quality"] = make_gate(
        "PASS" if data_pass else "FAIL",
        "V3 enrichment has complete price, move, RVOL, spread, and quote-age coverage." if data_pass else "V3 enrichment is missing required market data.",
        {
            "rows": enrich_h.get("rows"),
            "rows_with_price": enrich_h.get("rows_with_price"),
            "rows_with_day_move": enrich_h.get("rows_with_day_move"),
            "rows_with_non_default_rvol": enrich_h.get("rows_with_non_default_rvol"),
            "rows_with_spread": enrich_h.get("rows_with_spread"),
            "rows_with_quote_age": enrich_h.get("rows_with_quote_age"),
        },
    )

    # Gate 3: market regime
    regime = str(regime_h.get("regime") or "UNKNOWN").upper()
    regime_score = regime_h.get("regime_score")
    if regime == "RISK_ON":
        regime_status = "PASS"
        regime_reason = "Market regime is supportive for momentum research."
    elif regime == "NEUTRAL":
        regime_status = "WATCH"
        regime_reason = "Market regime is neutral. Require stronger setup confirmation."
    elif regime == "RISK_OFF":
        regime_status = "CAUTION"
        regime_reason = "Market regime is risk-off. Weak setups should be blocked."
    else:
        regime_status = "WATCH"
        regime_reason = "Market regime is unknown."
    gates["market_regime"] = make_gate(regime_status, regime_reason, {"regime": regime, "score": regime_score})

    # Gate 4: pre-breakout
    pre_status_raw = str((pre_row or {}).get("prebreakout_status_v3") or "").upper()
    pre_score = f((pre_row or {}).get("prebreakout_score_v3"))
    pre_blockers = (pre_row or {}).get("prebreakout_blockers_v3") or (pre_row or {}).get("blockers") or []
    if pre_status_raw in {"PRE_BREAKOUT", "BREAKOUT_TRIGGER", "BUY_SETUP", "RESEARCH_WATCH"} or pre_score >= 65:
        pre_status = "PASS" if pre_score >= 70 else "WATCH"
        pre_reason = "Pre-breakout setup is forming." if pre_status == "PASS" else "Pre-breakout setup is present but needs confirmation."
    elif pre_status_raw in {"CHASE_RISK_EXTENDED", "WAIT_FOR_PULLBACK"}:
        pre_status = "CHASE_RISK"
        pre_reason = "Ticker appears extended. Wait for pullback."
    elif pre_row:
        pre_status = "BLOCKED"
        pre_reason = "Pre-breakout gate did not pass."
    else:
        pre_status = "MISSING"
        pre_reason = "No pre-breakout row found."
    gates["pre_breakout"] = make_gate(pre_status, pre_reason, {"score": pre_score, "status": pre_status_raw, "blockers": pre_blockers})

    # Gate 5: reactive
    reactive_status_raw = str((reactive_row or {}).get("research_alert_status_v3") or (reactive_row or {}).get("status") or "").upper()
    reactive_score = f((reactive_row or {}).get("research_alert_score_v3"))
    day_move = f((reactive_row or pre_row or {}).get("day_move_pct"))
    reactive_blockers = (reactive_row or {}).get("research_alert_blockers_v3") or (reactive_row or {}).get("blockers") or []

    if reactive_status_raw in {"RESEARCH_BUY_ALERT", "RESEARCH_WATCH"} or reactive_score >= 65:
        if day_move >= 18:
            reactive_status = "CHASE_RISK"
            reactive_reason = "Reactive momentum exists, but day move is extended."
        else:
            reactive_status = "PASS" if reactive_score >= 70 else "WATCH"
            reactive_reason = "Reactive momentum is usable for review." if reactive_status == "PASS" else "Reactive setup is watch-only."
    elif reactive_row:
        reactive_status = "BLOCKED"
        reactive_reason = "Reactive momentum gate did not pass."
    else:
        reactive_status = "MISSING"
        reactive_reason = "No reactive row found."
    gates["reactive_momentum"] = make_gate(
        reactive_status,
        reactive_reason,
        {"score": reactive_score, "status": reactive_status_raw, "day_move_pct": day_move, "blockers": reactive_blockers},
    )

    # Gate 6: mathematical edge
    edge_status_raw = str((edge_row or {}).get("edge_status") or "").upper()
    positive_edge = (edge_row or {}).get("positive_edge") is True
    ev_pct = f((edge_row or {}).get("expected_value_pct"))
    edge_score = f((edge_row or {}).get("edge_score"))
    win_p = (edge_row or {}).get("estimated_win_probability")
    rr = (edge_row or {}).get("risk_reward_ratio")

    if positive_edge and ev_pct > 0:
        edge_status = "PASS"
        edge_reason = "Positive expected value candidate."
    elif edge_row and ev_pct > 0:
        edge_status = "WATCH"
        edge_reason = "Small positive edge. Review only."
    elif edge_row:
        edge_status = "FAIL"
        edge_reason = "Math edge is not positive."
    else:
        edge_status = "MISSING"
        edge_reason = "No mathematical edge row found."
    gates["math_edge"] = make_gate(
        edge_status,
        edge_reason,
        {
            "edge_status": edge_status_raw,
            "edge_score": edge_score,
            "expected_value_pct": ev_pct,
            "estimated_win_probability": win_p,
            "risk_reward_ratio": rr,
        },
    )

    # Gate 7: paper plan
    if plan_row:
        plan_status = "PASS"
        plan_reason = "Paper-plan-only candidate exists for review."
    else:
        plan_status = "MISSING"
        plan_reason = "No paper plan exists for this ticker."
    gates["paper_plan_only"] = make_gate(
        plan_status,
        plan_reason,
        {
            "planned_shares": (plan_row or {}).get("planned_shares"),
            "planned_notional": (plan_row or {}).get("planned_notional"),
            "target_price": (plan_row or {}).get("target_price"),
            "stop_price": (plan_row or {}).get("stop_price"),
            "order_submission": (plan_row or {}).get("order_submission", False),
            "live_trading": (plan_row or {}).get("live_trading", False),
        },
    )

    # Final verdict
    if not safety_pass:
        final_verdict = "SAFETY FAIL"
        action = "Do nothing. Safety lock must pass first."
    elif not data_pass:
        final_verdict = "DATA FAIL"
        action = "Do nothing. Market data quality is not trusted."
    elif regime == "RISK_OFF" and edge_status != "PASS":
        final_verdict = "WATCH ONLY"
        action = "Risk-off market. Only review strongest positive-edge setups."
    elif pre_status == "CHASE_RISK" or reactive_status == "CHASE_RISK":
        final_verdict = "WAIT FOR PULLBACK"
        action = "Do not chase. Wait for cleaner entry."
    elif pre_status == "PASS" and edge_status == "PASS" and plan_status == "PASS":
        final_verdict = "BUY SETUP - PLAN ONLY"
        action = "Review only. No paper or live order submitted."
    elif reactive_status == "PASS" and edge_status == "PASS" and plan_status == "PASS":
        final_verdict = "SCALP SETUP - PLAN ONLY"
        action = "Review only. Reactive scalp setup. No order submitted."
    elif edge_status in {"WATCH", "PASS"} and (pre_status in {"WATCH", "PASS"} or reactive_status in {"WATCH", "PASS"}):
        final_verdict = "RESEARCH WATCH"
        action = "Track only. Needs stronger confirmation."
    elif pre_status == "BLOCKED" and reactive_status == "BLOCKED":
        final_verdict = "BLOCKED"
        action = "No action. Setup gates failed."
    else:
        final_verdict = "WATCH ONLY"
        action = "Track only. No order submitted."

    return {
        "ticker": sym,
        "final_verdict": final_verdict,
        "action": action,
        "phase_gates": gates,
        "price": (plan_row or edge_row or reactive_row or pre_row or {}).get("live_price") or (plan_row or edge_row or reactive_row or pre_row or {}).get("price"),
        "day_move_pct": (reactive_row or pre_row or edge_row or {}).get("day_move_pct"),
        "relative_volume": (reactive_row or pre_row or edge_row or {}).get("relative_volume"),
        "expected_value_pct": ev_pct,
        "edge_score": edge_score,
        "planned_notional": (plan_row or {}).get("planned_notional"),
        "target_price": (plan_row or edge_row or {}).get("target_price"),
        "stop_price": (plan_row or edge_row or {}).get("stop_price"),
        "order_submission": False,
        "live_trading": False,
    }


def main() -> None:
    generated_at = now_iso()

    enrich_h = read_json(ENRICH_HEALTH, {})
    regime_h = read_json(REGIME_HEALTH, {})
    pre = read_json(PRE, {})
    pre_h = read_json(PRE_HEALTH, {})
    reactive = read_json(REACTIVE, {})
    reactive_h = read_json(REACTIVE_HEALTH, {})
    edge = read_json(EDGE, {})
    edge_h = read_json(EDGE_HEALTH, {})
    paper = read_json(PAPER_PLAN, {})
    paper_h = read_json(PAPER_PLAN_HEALTH, {})
    safety_h = read_json(SAFETY, {})
    package_100 = read_json(PACKAGE_100, {})
    morning = read_json(MORNING, {})

    blockers: list[str] = []
    warnings: list[str] = []

    if safety_h.get("status") != "PASS":
        blockers.append("hard_safety_lock_not_pass")
    if enrich_h.get("status") != "PASS":
        blockers.append("data_enrichment_not_pass")
    if package_100.get("status") not in {"PASS", "WARN"}:
        warnings.append("package_100_not_pass_or_warn")

    pre_rows = rows(pre, "candidates")
    reactive_rows = rows(reactive, "candidates")
    edge_rows = rows(edge, "candidates")
    plan_rows = rows(paper, "plans")

    # Include all tickers from strongest downstream layers first.
    symbols: list[str] = []
    for source in (plan_rows, edge_rows, pre_rows, reactive_rows):
        for r in source:
            sym = ticker(r)
            if sym and sym not in symbols:
                symbols.append(sym)

    pre_by = index_by_ticker(pre_rows)
    reactive_by = index_by_ticker(reactive_rows)
    edge_by = index_by_ticker(edge_rows)
    plan_by = index_by_ticker(plan_rows)

    context = {
        "enrich_h": enrich_h,
        "regime_h": regime_h,
        "safety_h": safety_h,
    }

    verdicts = [
        build_verdict(
            sym,
            pre_by.get(sym),
            reactive_by.get(sym),
            edge_by.get(sym),
            plan_by.get(sym),
            context,
        )
        for sym in symbols
    ]

    verdict_rank = {
        "BUY SETUP - PLAN ONLY": 100,
        "SCALP SETUP - PLAN ONLY": 90,
        "RESEARCH WATCH": 70,
        "WATCH ONLY": 50,
        "WAIT FOR PULLBACK": 40,
        "BLOCKED": 20,
        "DATA FAIL": 10,
        "SAFETY FAIL": 0,
    }

    verdicts.sort(
        key=lambda r: (
            verdict_rank.get(r.get("final_verdict"), 0),
            f(r.get("expected_value_pct")),
            f(r.get("edge_score")),
        ),
        reverse=True,
    )

    counts: dict[str, int] = {}
    for r in verdicts:
        v = r["final_verdict"]
        counts[v] = counts.get(v, 0) + 1

    buy_setups = [r for r in verdicts if r["final_verdict"] == "BUY SETUP - PLAN ONLY"]
    scalp_setups = [r for r in verdicts if r["final_verdict"] == "SCALP SETUP - PLAN ONLY"]
    research_watch = [r for r in verdicts if r["final_verdict"] == "RESEARCH WATCH"]

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "v3_phase_gate_verdict_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "verdict_count": len(verdicts),
        "buy_setup_plan_only_count": len(buy_setups),
        "scalp_setup_plan_only_count": len(scalp_setups),
        "research_watch_count": len(research_watch),
        "top_ticker": verdicts[0]["ticker"] if verdicts else None,
        "top_verdict": verdicts[0]["final_verdict"] if verdicts else None,
        "market_regime": regime_h.get("regime"),
        "package_100_status": package_100.get("status"),
        "morning_readiness": morning.get("readiness"),
        "safe_for_research": safety_h.get("safe_for_research"),
        "safe_for_paper_submission": False,
        "safe_for_live_trading": False,
        "order_submission": False,
        "live_trading": False,
    }

    out = {
        "schema_version": "v3_phase_gate_verdict_v1",
        "generated_at": generated_at,
        "health": health,
        "verdict_counts": counts,
        "verdicts": verdicts,
        "top_verdicts": verdicts[:10],
        "safety": {
            "phase_gate_only": True,
            "paper_plan_only": True,
            "order_submission": False,
            "live_trading": False,
        },
    }

    write_json(OUT_DOCS, out)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, out)

    print(json.dumps(health, indent=2))

    if status == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
