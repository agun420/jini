"""
Backtest Gate
=============
Primary source: V3 outcome journals (prebreakout + reactive) which have real
closed-trade results from the paper-simulation pipeline.

Falls back to legacy backtest_health.json only when journals are absent.

Gates operator_dashboard rows to WATCH_ONLY when historical evidence is weak.
Does NOT submit orders. Does NOT enable live trading.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

# Primary: V3 outcome journals — real closed trades with full return data.
V3_PRE_HEALTH     = DOCS / "v3_prebreakout_outcome_journal_health.json"
V3_REACTIVE_HEALTH = DOCS / "v3_research_alert_outcome_journal_health.json"
V3_OUTCOME_AUDIT  = DOCS / "v3_outcome_quality_audit.json"

# Fallback: legacy historical backtest of operator_dashboard rows.
BACKTEST_HEALTH   = DOCS / "backtest_health.json"

OPERATOR_DASHBOARD = DOCS / "operator_dashboard.json"
OPERATOR_HEALTH    = DOCS / "operator_health.json"

OUT_DASH   = DOCS / "operator_dashboard_backtest_gated.json"
OUT_HEALTH = DOCS / "backtest_gate_health.json"
OUT_STATE  = STATE / "backtest_gate_health.json"

# Gate thresholds — derived from backtest evidence.
MIN_PROFIT_FACTOR    = 1.0
MIN_TARGET_HIT_EDGE  = 0.0   # target_hit_rate must exceed stop_hit_rate
MIN_AVG_RETURN       = 0.0
MIN_CLOSED_TRADES    = 10    # require at least 10 real closed trades


def now() -> str:
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


def rows_from(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "signals", "candidates", "items", "data", "predictions"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _compute_from_v3_journals() -> dict[str, Any] | None:
    """
    Build gate metrics from V3 outcome journals.
    Returns None if journals are missing or have no closed trades.
    """
    pre      = read_json(V3_PRE_HEALTH, {})
    reactive = read_json(V3_REACTIVE_HEALTH, {})
    audit    = read_json(V3_OUTCOME_AUDIT, {})
    summary  = audit.get("summary", {})

    pre_closed      = f(pre.get("closed_alerts"))
    reactive_closed = f(reactive.get("closed_alerts"))
    total_closed    = pre_closed + reactive_closed

    if total_closed < MIN_CLOSED_TRADES:
        return None

    # Weighted-average target / stop hit rates.
    pre_thr      = f(pre.get("target_hit_rate_pct"))
    reactive_thr  = f(reactive.get("target_hit_rate_pct"))  # not in reactive health; compute below
    pre_shr      = f(pre.get("stop_hit_rate_pct"))
    pre_avg      = f(pre.get("avg_closed_return_pct"))
    reactive_avg = f(reactive.get("avg_closed_return_pct"))

    # Reactive stop_hit_rate from outcome audit (more detailed).
    r_summary = summary.get("reactive", {})
    reactive_thr  = f(r_summary.get("target_hit_rate_pct"), reactive_thr)
    reactive_shr  = f(r_summary.get("stop_hit_rate_pct"))

    # Weighted averages.
    total = pre_closed + reactive_closed
    target_hit  = (pre_thr  * pre_closed + reactive_thr  * reactive_closed) / total
    stop_hit    = (pre_shr  * pre_closed + reactive_shr  * reactive_closed) / total
    avg_return  = (pre_avg  * pre_closed + reactive_avg  * reactive_closed) / total

    # Profit factor from outcome quality audit.
    pre_s  = summary.get("prebreakout", {})
    rea_s  = summary.get("reactive", {})
    pre_wins = f(pre_s.get("target_hits"))
    pre_win_avg = f(pre_s.get("avg_win_pct"), 0.7437)
    pre_loss_avg = abs(f(pre_s.get("avg_loss_pct"), -0.5346))
    pre_losses = f(pre_s.get("stop_hits")) + f(pre_s.get("time_exits")) * (
        1.0 - f(pre_s.get("win_rate_pct"), 57.36) / 100.0
    )

    rea_wins = f(rea_s.get("target_hits"))
    rea_win_avg = f(rea_s.get("avg_win_pct"), 0.6424)
    rea_loss_avg = abs(f(rea_s.get("avg_loss_pct"), -0.6029))
    rea_losses = f(rea_s.get("stop_hits")) + f(rea_s.get("time_exits")) * (
        1.0 - f(rea_s.get("win_rate_pct"), 59.52) / 100.0
    )

    gross_profit = pre_wins * pre_win_avg + rea_wins * rea_win_avg
    gross_loss   = pre_losses * pre_loss_avg + rea_losses * rea_loss_avg
    profit_factor = round(gross_profit / gross_loss, 4) if gross_loss > 0 else 0.0

    return {
        "source": "v3_outcome_journals",
        "total_closed": int(total_closed),
        "pre_closed": int(pre_closed),
        "reactive_closed": int(reactive_closed),
        "target_hit_rate_pct": round(target_hit, 4),
        "stop_hit_rate_pct": round(stop_hit, 4),
        "avg_return_pct": round(avg_return, 6),
        "profit_factor": profit_factor,
    }


def _compute_from_legacy() -> dict[str, Any]:
    """Fallback: legacy backtest_health.json from historical scanner backtest."""
    backtest = read_json(BACKTEST_HEALTH, {})
    return {
        "source": "legacy_backtest_health",
        "total_closed": int(f(backtest.get("total_tests"))),
        "pre_closed": 0,
        "reactive_closed": 0,
        "target_hit_rate_pct": f(backtest.get("target_hit_rate_pct")),
        "stop_hit_rate_pct": f(backtest.get("stop_hit_rate_pct")),
        "avg_return_pct": f(backtest.get("avg_return_pct")),
        "profit_factor": f(backtest.get("profit_factor")),
    }


def main() -> None:
    generated_at = now()

    # Prefer V3 journal data; fall back to legacy only when journals are missing.
    metrics = _compute_from_v3_journals() or _compute_from_legacy()
    source         = metrics["source"]
    profit_factor  = metrics["profit_factor"]
    target_hit     = metrics["target_hit_rate_pct"]
    stop_hit       = metrics["stop_hit_rate_pct"]
    avg_return     = metrics["avg_return_pct"]
    total_closed   = metrics["total_closed"]

    operator       = read_json(OPERATOR_DASHBOARD, {})
    operator_health = read_json(OPERATOR_HEALTH, {})
    rows           = rows_from(operator)

    blockers: list[str] = []
    warnings: list[str] = []

    if source == "legacy_backtest_health" and not read_json(BACKTEST_HEALTH, {}):
        blockers.append("backtest_health_missing")

    if total_closed < MIN_CLOSED_TRADES:
        blockers.append(f"insufficient_closed_trades_{total_closed}")

    if profit_factor < MIN_PROFIT_FACTOR:
        blockers.append("profit_factor_below_1")

    if (target_hit - stop_hit) <= MIN_TARGET_HIT_EDGE:
        blockers.append("target_hit_rate_not_above_stop_hit_rate")

    if avg_return < MIN_AVG_RETURN:
        blockers.append("avg_return_negative")

    gate_active = bool(blockers)

    gated_rows = []
    gated_count = 0

    for row in rows:
        new = dict(row)

        new["backtest_gate_active"]         = gate_active
        new["backtest_profit_factor"]       = profit_factor
        new["backtest_avg_return_pct"]      = avg_return
        new["backtest_target_hit_rate_pct"] = target_hit
        new["backtest_stop_hit_rate_pct"]   = stop_hit
        new["backtest_source"]              = source

        if gate_active:
            original_status = new.get("score_status") or new.get("operator_status")
            new["score_status_before_backtest_gate"]    = original_status
            new["operator_status_before_backtest_gate"] = new.get("operator_status")
            new["score_status"]        = "WATCH_ONLY"
            new["operator_status"]     = "BACKTEST_GATE_ACTIVE"
            new["trade_gate"]          = "Blocked"
            new["trade_gate_reasons"]  = list(dict.fromkeys(
                list(new.get("trade_gate_reasons") or []) + blockers
            ))
            new["alert_eligible"]            = False
            new["buy_setup_alert_blocked"]   = True
            new["paper_order_allowed"]       = False
            new["live_order_allowed"]        = False
            gated_count += 1

        new["order_submission"] = False
        new["live_trading"]     = False
        gated_rows.append(new)

    status = "PASS"
    if gate_active:
        status = "WARN"
        warnings.append("backtest_gate_active_trade_eligibility_blocked")

    health = {
        "schema_version": "backtest_gate_health_v2",
        "generated_at": generated_at,
        "status": status,
        "gate_active": gate_active,
        "blockers": blockers,
        "warnings": warnings,
        "rows": len(rows),
        "gated_rows": gated_count,
        "source": source,
        "total_closed_trades": total_closed,
        "profit_factor": profit_factor,
        "target_hit_rate_pct": target_hit,
        "stop_hit_rate_pct": stop_hit,
        "avg_return_pct": avg_return,
        "operator_health_status": operator_health.get("status"),
        "order_submission": False,
        "live_trading": False,
        "message": (
            "Backtest gate uses V3 outcome journals (prebreakout + reactive) as the "
            "primary evidence source. Falls back to legacy historical backtest if journals "
            "are absent. Rows remain visible as watch-only research signals when gate active."
        ),
    }

    output = {
        "schema_version": "operator_dashboard_backtest_gated_v2",
        "generated_at": generated_at,
        "status": status,
        "health": health,
        "rows": gated_rows,
        "safety": {
            "paper_only": True,
            "order_submission": False,
            "live_trading": False,
            "message": "Backtest-gated operator dashboard only. No live trading or order submission.",
        },
    }

    write_json(OUT_DASH, output)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, health)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
