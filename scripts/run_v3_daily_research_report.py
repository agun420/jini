from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

AUDIT = DOCS / "v3_outcome_quality_audit.json"
PRE_JOURNAL = DOCS / "v3_prebreakout_outcome_journal.json"
REACTIVE_JOURNAL = DOCS / "v3_research_alert_outcome_journal.json"
PRE_HEALTH = DOCS / "v3_prebreakout_predictor_health.json"
REACTIVE_HEALTH = DOCS / "v3_research_alert_score_health.json"
MARKET_REGIME_HEALTH = DOCS / "v3_market_regime_filter_health.json"
FINAL_REPO_AUDIT_HEALTH = DOCS / "final_repo_audit.json"

OUT_DOCS = DOCS / "v3_daily_research_report.json"
OUT_HEALTH = DOCS / "v3_daily_research_report_health.json"
OUT_STATE = STATE / "v3_daily_research_report.json"


VALID_REASONS = {"TARGET_HIT", "STOP_HIT", "TIME_EXIT"}


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


def valid_closed(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("closed_alerts") or []
    return [
        r for r in rows
        if isinstance(r, dict)
        and r.get("exit_reason") in VALID_REASONS
        and r.get("return_pct") is not None
    ]


def best_worst(rows: list[dict[str, Any]], n: int = 10) -> dict[str, Any]:
    ranked = sorted(rows, key=lambda r: f(r.get("return_pct")), reverse=True)

    def slim(r: dict[str, Any]) -> dict[str, Any]:
        return {
            "ticker": r.get("ticker"),
            "setup_status": r.get("setup_status"),
            "entry_price": r.get("entry_price"),
            "exit_price": r.get("exit_price"),
            "exit_reason": r.get("exit_reason"),
            "return_pct": r.get("return_pct"),
            "score": r.get("prebreakout_score_v3") or r.get("research_alert_score_v3"),
            "day_move_pct": r.get("day_move_pct"),
            "relative_volume": r.get("relative_volume"),
            "vwap_distance_pct": r.get("vwap_distance_pct"),
            "opened_at": r.get("opened_at"),
            "closed_at": r.get("closed_at"),
        }

    return {
        "best": [slim(r) for r in ranked[:n]],
        "worst": [slim(r) for r in list(reversed(ranked[-n:]))],
    }


def count_reasons(rows: list[dict[str, Any]]) -> dict[str, int]:
    out = {"TARGET_HIT": 0, "STOP_HIT": 0, "TIME_EXIT": 0}
    for r in rows:
        reason = str(r.get("exit_reason") or "")
        if reason in out:
            out[reason] += 1
    return out


def layer_summary_from_audit(summary: dict[str, Any], key: str) -> dict[str, Any]:
    src = summary.get(key, {}) if isinstance(summary, dict) else {}
    return {
        "total_alerts": int(f(src.get("total_alerts"))),
        "closed_alerts": int(f(src.get("closed_alerts"))),
        "target_hits": int(f(src.get("target_hits"))),
        "stop_hits": int(f(src.get("stop_hits"))),
        "time_exits": int(f(src.get("time_exits"))),
        "target_hit_rate_pct": f(src.get("target_hit_rate_pct")),
        "stop_hit_rate_pct": f(src.get("stop_hit_rate_pct")),
        "time_exit_rate_pct": f(src.get("time_exit_rate_pct")),
        "avg_return_pct": f(src.get("avg_return_pct")),
        "win_rate_pct": f(src.get("win_rate_pct")),
        "avg_win_pct": f(src.get("avg_win_pct")),
        "avg_loss_pct": f(src.get("avg_loss_pct")),
    }


def main() -> None:
    generated_at = now_iso()

    audit = read_json(AUDIT, {})
    pre_journal = read_json(PRE_JOURNAL, {})
    reactive_journal = read_json(REACTIVE_JOURNAL, {})
    pre_health = read_json(PRE_HEALTH, {})
    reactive_health = read_json(REACTIVE_HEALTH, {})
    market_regime = read_json(MARKET_REGIME_HEALTH, {})
    final_repo = read_json(FINAL_REPO_AUDIT_HEALTH, {})

    summary = audit.get("summary", {})
    pre_summary = layer_summary_from_audit(summary, "prebreakout")
    reactive_summary = layer_summary_from_audit(summary, "reactive")

    pre_rows = valid_closed(pre_journal)
    reactive_rows = valid_closed(reactive_journal)

    pre_avg = f(pre_summary.get("avg_return_pct"))
    reactive_avg = f(reactive_summary.get("avg_return_pct"))
    pre_closed = int(f(pre_summary.get("closed_alerts")))
    reactive_closed = int(f(reactive_summary.get("closed_alerts")))
    pre_hit = f(pre_summary.get("target_hit_rate_pct"))
    reactive_hit = f(reactive_summary.get("target_hit_rate_pct"))

    if pre_avg > reactive_avg:
        winning_layer = "PRE_BREAKOUT"
    elif reactive_avg > pre_avg:
        winning_layer = "REACTIVE"
    else:
        winning_layer = "TIE"

    gap = round(abs(pre_avg - reactive_avg), 4)

    blockers: list[str] = []
    warnings: list[str] = []

    if pre_closed < 50:
        warnings.append("prebreakout_sample_under_50")
    if reactive_closed < 50:
        warnings.append("reactive_sample_under_50")
    if pre_avg <= 0:
        warnings.append("prebreakout_avg_not_positive")
    if reactive_avg <= 0:
        warnings.append("reactive_avg_not_positive")
    if final_repo.get("status") == "FAIL":
        warnings.append("final_repo_audit_has_blockers")
    if market_regime.get("regime") == "RISK_OFF":
        warnings.append("market_regime_risk_off")

    # Promotion decision.
    promotion_decision = "KEEP_RESEARCH_ONLY"

    if (
        pre_closed >= 50
        and reactive_closed >= 50
        and pre_avg > 0
        and reactive_avg > 0
        and gap <= 0.05
    ):
        promotion_decision = "BOTH_LAYERS_RESEARCH_VALIDATED_KEEP_COLLECTING"

    if reactive_avg > pre_avg and gap > 0.05:
        promotion_decision = "REACTIVE_LEADS_KEEP_PREBREAKOUT_PRIMARY_WATCH"

    if pre_avg > reactive_avg and gap > 0.05:
        promotion_decision = "PREBREAKOUT_LEADS_KEEP_REACTIVE_SECONDARY"

    # Paper trade readiness is intentionally conservative.
    paper_trade_ready = False
    paper_trade_reason = "Need 3 to 5 clean market days and 100+ closed alerts per layer before paper-order activation."

    if (
        pre_closed >= 100
        and reactive_closed >= 100
        and pre_avg > 0.15
        and reactive_avg > 0.15
        and pre_hit >= 40
        and reactive_hit >= 40
        and final_repo.get("status") != "FAIL"
    ):
        paper_trade_reason = "Research results are improving, but still require multi-day confirmation before enabling paper submission."

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "v3_daily_research_report_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "winning_layer": winning_layer,
        "avg_return_gap_pct": gap,
        "promotion_decision": promotion_decision,
        "prebreakout_closed": pre_closed,
        "prebreakout_target_hit_rate_pct": round(pre_hit, 2),
        "prebreakout_avg_return_pct": round(pre_avg, 4),
        "reactive_closed": reactive_closed,
        "reactive_target_hit_rate_pct": round(reactive_hit, 2),
        "reactive_avg_return_pct": round(reactive_avg, 4),
        "current_prebreakout_top_ticker": pre_health.get("top_ticker"),
        "current_prebreakout_top_status": pre_health.get("top_status"),
        "current_reactive_top_ticker": reactive_health.get("top_ticker"),
        "market_regime": market_regime.get("regime"),
        "market_regime_score": market_regime.get("regime_score"),
        "market_regime_recommendation": market_regime.get("recommendation"),
        "paper_trade_ready": paper_trade_ready,
        "paper_trade_reason": paper_trade_reason,
        "order_submission": False,
        "live_trading": False,
    }

    report = {
        "schema_version": "v3_daily_research_report_v1",
        "generated_at": generated_at,
        "health": health,
        "executive_summary": {
            "read": (
                "Both layers are positive. Keep pre-breakout as the main research view "
                "and reactive as the secondary scalp view until more market days validate the edge."
            ),
            "winning_layer": winning_layer,
            "avg_return_gap_pct": gap,
            "promotion_decision": promotion_decision,
            "paper_trade_decision": "DO_NOT_ENABLE_PAPER_ORDERS_YET",
            "paper_trade_reason": paper_trade_reason,
        },
        "layer_summary": {
            "prebreakout": pre_summary,
            "reactive": reactive_summary,
        },
        "reason_counts": {
            "prebreakout": count_reasons(pre_rows),
            "reactive": count_reasons(reactive_rows),
        },
        "top_bottom": {
            "prebreakout": best_worst(pre_rows),
            "reactive": best_worst(reactive_rows),
        },
        "current_state": {
            "prebreakout_health": pre_health,
            "reactive_health": reactive_health,
            "market_regime": market_regime,
            "final_repo_audit_status": final_repo.get("status"),
            "final_repo_audit_blockers": final_repo.get("score", {}).get("blockers", []),
        },
        "recommendations": [
            "Keep both layers in research-only mode.",
            "Keep pre-breakout as the primary dashboard layer.",
            "Keep reactive as the secondary scalp layer with no-chase protection.",
            "Collect at least 3 to 5 market days before paper-order activation.",
            "Fix any final repo audit blockers before considering paper submission.",
            "Do not enable live trading.",
        ],
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "paper_trade_ready": paper_trade_ready,
        },
    }

    write_json(OUT_DOCS, report)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, report)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
