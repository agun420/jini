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

OUT_DOCS = DOCS / "v3_daily_research_report.json"
OUT_HEALTH = DOCS / "v3_daily_research_report_health.json"
OUT_STATE = STATE / "v3_daily_research_report.json"


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
        and r.get("exit_reason") in {"TARGET_HIT", "STOP_HIT", "TIME_EXIT"}
        and r.get("return_pct") is not None
    ]


def best_worst(rows: list[dict[str, Any]], n: int = 8) -> dict[str, Any]:
    ranked = sorted(rows, key=lambda r: f(r.get("return_pct")), reverse=True)
    return {
        "best": ranked[:n],
        "worst": list(reversed(ranked[-n:])),
    }


def main() -> None:
    generated_at = now_iso()

    audit = read_json(AUDIT, {})
    pre_journal = read_json(PRE_JOURNAL, {})
    reactive_journal = read_json(REACTIVE_JOURNAL, {})
    pre_health = read_json(PRE_HEALTH, {})
    reactive_health = read_json(REACTIVE_HEALTH, {})

    audit_health = audit.get("health", {})
    summary = audit.get("summary", {})

    pre_summary = summary.get("prebreakout", {})
    reactive_summary = summary.get("reactive", {})

    pre_avg = f(pre_summary.get("avg_return_pct"))
    reactive_avg = f(reactive_summary.get("avg_return_pct"))

    pre_hit = f(pre_summary.get("target_hit_rate_pct"))
    reactive_hit = f(reactive_summary.get("target_hit_rate_pct"))

    pre_closed = int(f(pre_summary.get("closed_alerts")))
    reactive_closed = int(f(reactive_summary.get("closed_alerts")))

    pre_rows = valid_closed(pre_journal)
    reactive_rows = valid_closed(reactive_journal)

    if pre_avg > reactive_avg:
        winning_layer = "PRE_BREAKOUT"
    elif reactive_avg > pre_avg:
        winning_layer = "REACTIVE"
    else:
        winning_layer = "TIE"

    gap = round(abs(pre_avg - reactive_avg), 4)

    promotion_decision = "HOLD_RESEARCH_ONLY"
    if pre_closed >= 50 and reactive_closed >= 50 and pre_avg > 0 and reactive_avg > 0 and gap < 0.05:
        promotion_decision = "BOTH_LAYERS_RESEARCH_VALIDATED_KEEP_COLLECTING"
    if reactive_avg > pre_avg and gap >= 0.10:
        promotion_decision = "REACTIVE_LEADS_KEEP_PREBREAKOUT_WATCH_ONLY"
    if pre_avg > reactive_avg and gap >= 0.10:
        promotion_decision = "PREBREAKOUT_LEADS_KEEP_REACTIVE_SECONDARY"

    blockers = []
    warnings = []

    if pre_closed < 50:
        warnings.append("prebreakout_sample_under_50")
    if reactive_closed < 50:
        warnings.append("reactive_sample_under_50")

    if pre_avg <= 0:
        warnings.append("prebreakout_avg_not_positive")
    if reactive_avg <= 0:
        warnings.append("reactive_avg_not_positive")

    # Paper/live remain explicitly blocked.
    health = {
        "schema_version": "v3_daily_research_report_health_v1",
        "generated_at": generated_at,
        "status": "PASS" if not blockers else "FAIL",
        "blockers": blockers,
        "warnings": warnings,
        "winning_layer": winning_layer,
        "avg_return_gap_pct": gap,
        "promotion_decision": promotion_decision,
        "prebreakout_closed": pre_closed,
        "prebreakout_target_hit_rate_pct": pre_hit,
        "prebreakout_avg_return_pct": pre_avg,
        "reactive_closed": reactive_closed,
        "reactive_target_hit_rate_pct": reactive_hit,
        "reactive_avg_return_pct": reactive_avg,
        "current_prebreakout_top_ticker": pre_health.get("top_ticker"),
        "current_prebreakout_top_status": pre_health.get("top_status"),
        "current_reactive_top_ticker": reactive_health.get("top_ticker"),
        "paper_trade_ready": False,
        "order_submission": False,
        "live_trading": False,
    }

    report = {
        "schema_version": "v3_daily_research_report_v1",
        "generated_at": generated_at,
        "health": health,
        "executive_summary": {
            "read": "Both research layers are positive. Reactive is slightly ahead, but pre-breakout is now close enough to keep validating.",
            "winning_layer": winning_layer,
            "promotion_decision": promotion_decision,
            "paper_trade_decision": "DO_NOT_ENABLE_PAPER_ORDERS_YET",
            "reason": "One-day research data is useful but not enough for paper-order activation.",
        },
        "layer_summary": {
            "prebreakout": pre_summary,
            "reactive": reactive_summary,
        },
        "top_bottom": {
            "prebreakout": best_worst(pre_rows),
            "reactive": best_worst(reactive_rows),
        },
        "recommendations": [
            "Keep both layers in research-only mode.",
            "Keep pre-breakout as the primary dashboard layer.",
            "Keep reactive as secondary scalp layer with no-chase protection.",
            "Collect at least 3 to 5 market days before paper-order activation.",
            "Do not enable live trading.",
        ],
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "paper_trade_ready": False,
        },
    }

    write_json(OUT_DOCS, report)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, report)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
