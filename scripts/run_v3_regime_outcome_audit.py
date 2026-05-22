from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

PRE_JOURNAL = DOCS / "v3_prebreakout_outcome_journal.json"
REACTIVE_JOURNAL = DOCS / "v3_research_alert_outcome_journal.json"
MARKET_REGIME = DOCS / "v3_market_regime_filter_health.json"

OUT_DOCS = DOCS / "v3_regime_outcome_audit.json"
OUT_HEALTH = DOCS / "v3_regime_outcome_audit_health.json"
OUT_STATE = STATE / "v3_regime_outcome_audit.json"

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
        if v is None or v == "":
            return default
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except Exception:
        return default


def alerts_from(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path, {})
    rows = payload.get("alerts", [])
    if isinstance(rows, list):
        return [r for r in rows if isinstance(r, dict)]
    return []


def valid_closed(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        a for a in alerts
        if a.get("status") == "CLOSED"
        and a.get("exit_reason") in VALID_REASONS
        and a.get("return_pct") is not None
    ]


def get_regime(alert: dict[str, Any], fallback: str) -> str:
    return str(
        alert.get("market_regime")
        or alert.get("regime")
        or fallback
        or "UNKNOWN"
    ).upper()


def summarize(alerts: list[dict[str, Any]]) -> dict[str, Any]:
    closed = valid_closed(alerts)

    targets = [a for a in closed if a.get("exit_reason") == "TARGET_HIT"]
    stops = [a for a in closed if a.get("exit_reason") == "STOP_HIT"]
    time_exits = [a for a in closed if a.get("exit_reason") == "TIME_EXIT"]

    returns = [f(a.get("return_pct")) for a in closed]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]

    avg_return = sum(returns) / len(returns) if returns else 0.0

    return {
        "total_alerts": len(alerts),
        "closed_alerts": len(closed),
        "target_hits": len(targets),
        "stop_hits": len(stops),
        "time_exits": len(time_exits),
        "target_hit_rate_pct": round(len(targets) / len(closed) * 100, 2) if closed else 0.0,
        "stop_hit_rate_pct": round(len(stops) / len(closed) * 100, 2) if closed else 0.0,
        "time_exit_rate_pct": round(len(time_exits) / len(closed) * 100, 2) if closed else 0.0,
        "avg_return_pct": round(avg_return, 4),
        "win_rate_pct": round(len(wins) / len(closed) * 100, 2) if closed else 0.0,
        "avg_win_pct": round(sum(wins) / len(wins), 4) if wins else 0.0,
        "avg_loss_pct": round(sum(losses) / len(losses), 4) if losses else 0.0,
    }


def group_by_regime(alerts: list[dict[str, Any]], fallback_regime: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for a in valid_closed(alerts):
        groups[get_regime(a, fallback_regime)].append(a)

    out = {}
    for regime, rows in sorted(groups.items()):
        out[regime] = summarize(rows)
    return out


def best_worst(alerts: list[dict[str, Any]], fallback_regime: str, n: int = 8) -> dict[str, Any]:
    rows = valid_closed(alerts)

    slim = []
    for a in rows:
        slim.append({
            "ticker": a.get("ticker"),
            "regime": get_regime(a, fallback_regime),
            "setup_status": a.get("setup_status"),
            "entry_price": a.get("entry_price"),
            "exit_price": a.get("exit_price"),
            "exit_reason": a.get("exit_reason"),
            "return_pct": a.get("return_pct"),
            "score": a.get("prebreakout_score_v3") or a.get("research_alert_score_v3"),
            "day_move_pct": a.get("day_move_pct"),
            "relative_volume": a.get("relative_volume"),
            "opened_at": a.get("opened_at"),
            "closed_at": a.get("closed_at"),
        })

    slim.sort(key=lambda r: f(r.get("return_pct")), reverse=True)

    return {
        "best": slim[:n],
        "worst": list(reversed(slim[-n:])),
    }


def main() -> None:
    generated_at = now_iso()

    market = read_json(MARKET_REGIME, {})
    current_regime = str(market.get("regime") or "UNKNOWN").upper()
    current_regime_score = f(market.get("regime_score"))

    pre_alerts = alerts_from(PRE_JOURNAL)
    reactive_alerts = alerts_from(REACTIVE_JOURNAL)

    blockers: list[str] = []
    warnings: list[str] = []

    if not pre_alerts:
        warnings.append("no_prebreakout_alerts")
    if not reactive_alerts:
        warnings.append("no_reactive_alerts")
    if current_regime == "UNKNOWN":
        warnings.append("market_regime_unknown")

    pre_summary = summarize(pre_alerts)
    reactive_summary = summarize(reactive_alerts)

    pre_by_regime = group_by_regime(pre_alerts, current_regime)
    reactive_by_regime = group_by_regime(reactive_alerts, current_regime)

    recommendation = []

    # Conservative regime-aware guidance.
    if current_regime == "RISK_OFF":
        recommendation.append("risk_off_keep_only_strongest_alerts_research_only")
    elif current_regime == "RISK_ON":
        recommendation.append("risk_on_normal_research_alerting_allowed")
    elif current_regime == "NEUTRAL":
        recommendation.append("neutral_market_keep_tightened_rules")

    if pre_summary["avg_return_pct"] > 0 and reactive_summary["avg_return_pct"] > 0:
        recommendation.append("both_layers_positive_continue_collecting")
    if reactive_summary["avg_return_pct"] > pre_summary["avg_return_pct"]:
        recommendation.append("reactive_slightly_leads_but_monitor_chase_risk")
    if pre_summary["avg_return_pct"] > reactive_summary["avg_return_pct"]:
        recommendation.append("prebreakout_leads_promote_primary_research_view")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "v3_regime_outcome_audit_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "current_regime": current_regime,
        "current_regime_score": round(current_regime_score, 4),
        "prebreakout_closed": pre_summary["closed_alerts"],
        "prebreakout_avg_return_pct": pre_summary["avg_return_pct"],
        "reactive_closed": reactive_summary["closed_alerts"],
        "reactive_avg_return_pct": reactive_summary["avg_return_pct"],
        "recommendation": recommendation,
        "order_submission": False,
        "live_trading": False,
        "paper_order_allowed": False,
        "live_order_allowed": False,
    }

    out = {
        "schema_version": "v3_regime_outcome_audit_v1",
        "generated_at": generated_at,
        "health": health,
        "current_market_regime": market,
        "summary": {
            "prebreakout": pre_summary,
            "reactive": reactive_summary,
        },
        "by_regime": {
            "prebreakout": pre_by_regime,
            "reactive": reactive_by_regime,
        },
        "top_bottom": {
            "prebreakout": best_worst(pre_alerts, current_regime),
            "reactive": best_worst(reactive_alerts, current_regime),
        },
        "safety": {
            "purpose": "Regime-aware outcome audit only. Does not trade.",
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
