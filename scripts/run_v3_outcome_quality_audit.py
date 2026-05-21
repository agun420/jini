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

OUT_DOCS = DOCS / "v3_outcome_quality_audit.json"
OUT_HEALTH = DOCS / "v3_outcome_quality_audit_health.json"
OUT_STATE = STATE / "v3_outcome_quality_audit.json"


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
    alerts = payload.get("alerts", [])
    if isinstance(alerts, list):
        return [a for a in alerts if isinstance(a, dict)]
    return []


def valid_closed(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        a for a in alerts
        if a.get("status") == "CLOSED"
        and a.get("exit_reason") in VALID_REASONS
        and a.get("return_pct") is not None
    ]


def bucket_day_move(x: float) -> str:
    if x < 0:
        return "negative"
    if x < 2:
        return "0_to_2"
    if x < 5:
        return "2_to_5"
    if x < 8:
        return "5_to_8"
    if x < 12:
        return "8_to_12"
    if x < 20:
        return "12_to_20"
    return "20_plus_chase"


def bucket_score(x: float) -> str:
    if x < 52:
        return "under_52"
    if x < 60:
        return "52_to_60"
    if x < 68:
        return "60_to_68"
    if x < 75:
        return "68_to_75"
    return "75_plus"


def summarize(alerts: list[dict[str, Any]]) -> dict[str, Any]:
    closed = valid_closed(alerts)
    targets = [a for a in closed if a.get("exit_reason") == "TARGET_HIT"]
    stops = [a for a in closed if a.get("exit_reason") == "STOP_HIT"]
    time_exits = [a for a in closed if a.get("exit_reason") == "TIME_EXIT"]

    returns = [f(a.get("return_pct")) for a in closed]
    avg = sum(returns) / len(returns) if returns else 0.0

    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]

    return {
        "total_alerts": len(alerts),
        "closed_alerts": len(closed),
        "target_hits": len(targets),
        "stop_hits": len(stops),
        "time_exits": len(time_exits),
        "target_hit_rate_pct": round((len(targets) / len(closed) * 100), 2) if closed else 0.0,
        "stop_hit_rate_pct": round((len(stops) / len(closed) * 100), 2) if closed else 0.0,
        "time_exit_rate_pct": round((len(time_exits) / len(closed) * 100), 2) if closed else 0.0,
        "avg_return_pct": round(avg, 4),
        "win_rate_pct": round((len(wins) / len(closed) * 100), 2) if closed else 0.0,
        "avg_win_pct": round(sum(wins) / len(wins), 4) if wins else 0.0,
        "avg_loss_pct": round(sum(losses) / len(losses), 4) if losses else 0.0,
    }


def group_summary(alerts: list[dict[str, Any]], key_fn) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for a in valid_closed(alerts):
        groups[str(key_fn(a))].append(a)

    out: dict[str, Any] = {}
    for key, vals in groups.items():
        out[key] = summarize(vals)
    return dict(sorted(out.items()))


def top_bottom(alerts: list[dict[str, Any]], n: int = 10) -> dict[str, list[dict[str, Any]]]:
    closed = valid_closed(alerts)
    rows = [
        {
            "ticker": a.get("ticker"),
            "setup_status": a.get("setup_status"),
            "entry_price": a.get("entry_price"),
            "exit_price": a.get("exit_price"),
            "exit_reason": a.get("exit_reason"),
            "return_pct": a.get("return_pct"),
            "score": a.get("prebreakout_score_v3") or a.get("research_alert_score_v3"),
            "day_move_pct": a.get("day_move_pct"),
            "relative_volume": a.get("relative_volume"),
            "vwap_distance_pct": a.get("vwap_distance_pct"),
            "opened_at": a.get("opened_at"),
            "closed_at": a.get("closed_at"),
        }
        for a in closed
    ]

    rows.sort(key=lambda r: f(r.get("return_pct")), reverse=True)
    return {
        "best": rows[:n],
        "worst": list(reversed(rows[-n:])),
    }


def main() -> None:
    generated_at = now_iso()

    pre_alerts = alerts_from(PRE_JOURNAL)
    reactive_alerts = alerts_from(REACTIVE_JOURNAL)

    blockers: list[str] = []
    warnings: list[str] = []

    if not pre_alerts:
        warnings.append("no_prebreakout_alerts")
    if not reactive_alerts:
        warnings.append("no_reactive_alerts")

    pre_summary = summarize(pre_alerts)
    reactive_summary = summarize(reactive_alerts)

    recommendation = []

    if reactive_summary["avg_return_pct"] > pre_summary["avg_return_pct"]:
        recommendation.append("reactive_layer_currently_outperforming_prebreakout")
    if pre_summary["time_exit_rate_pct"] > 50:
        recommendation.append("prebreakout_layer_has_too_many_time_exits")
    if pre_summary["target_hit_rate_pct"] < 20:
        recommendation.append("prebreakout_target_hit_rate_too_low")
    if reactive_summary["target_hit_rate_pct"] >= 40:
        recommendation.append("reactive_layer_has_scalping_edge_but_watch_chase_risk")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "v3_outcome_quality_audit_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "prebreakout_closed": pre_summary["closed_alerts"],
        "prebreakout_target_hit_rate_pct": pre_summary["target_hit_rate_pct"],
        "prebreakout_avg_return_pct": pre_summary["avg_return_pct"],
        "reactive_closed": reactive_summary["closed_alerts"],
        "reactive_target_hit_rate_pct": reactive_summary["target_hit_rate_pct"],
        "reactive_avg_return_pct": reactive_summary["avg_return_pct"],
        "recommendation": recommendation,
        "order_submission": False,
        "live_trading": False,
    }

    out = {
        "schema_version": "v3_outcome_quality_audit_v1",
        "generated_at": generated_at,
        "health": health,
        "summary": {
            "prebreakout": pre_summary,
            "reactive": reactive_summary,
        },
        "prebreakout_breakdowns": {
            "by_setup_status": group_summary(pre_alerts, lambda a: a.get("setup_status") or "UNKNOWN"),
            "by_day_move_bucket": group_summary(pre_alerts, lambda a: bucket_day_move(f(a.get("day_move_pct")))),
            "by_score_bucket": group_summary(pre_alerts, lambda a: bucket_score(f(a.get("prebreakout_score_v3")))),
            "by_ticker": group_summary(pre_alerts, lambda a: a.get("ticker") or "UNKNOWN"),
        },
        "reactive_breakdowns": {
            "by_day_move_bucket": group_summary(reactive_alerts, lambda a: bucket_day_move(f(a.get("day_move_pct")))),
            "by_score_bucket": group_summary(reactive_alerts, lambda a: bucket_score(f(a.get("research_alert_score_v3")))),
            "by_ticker": group_summary(reactive_alerts, lambda a: a.get("ticker") or "UNKNOWN"),
        },
        "top_bottom": {
            "prebreakout": top_bottom(pre_alerts),
            "reactive": top_bottom(reactive_alerts),
        },
        "safety": {
            "purpose": "Outcome audit only. Does not trade.",
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
