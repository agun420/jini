from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

BACKTEST_HEALTH = DOCS / "backtest_health.json"
OPERATOR_DASHBOARD = DOCS / "operator_dashboard.json"
OPERATOR_HEALTH = DOCS / "operator_health.json"

OUT_DASH = DOCS / "operator_dashboard_backtest_gated.json"
OUT_HEALTH = DOCS / "backtest_gate_health.json"
OUT_STATE = STATE / "backtest_gate_health.json"


MIN_PROFIT_FACTOR = 1.0
MIN_TARGET_HIT_EDGE = 0.0
MIN_AVG_RETURN = 0.0


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


def main() -> None:
    generated_at = now()

    backtest = read_json(BACKTEST_HEALTH, {})
    operator = read_json(OPERATOR_DASHBOARD, {})
    operator_health = read_json(OPERATOR_HEALTH, {})

    rows = rows_from(operator)

    profit_factor = f(backtest.get("profit_factor"))
    target_hit = f(backtest.get("target_hit_rate_pct"))
    stop_hit = f(backtest.get("stop_hit_rate_pct"))
    avg_return = f(backtest.get("avg_return_pct"))

    blockers: list[str] = []
    warnings: list[str] = []

    if not backtest:
        blockers.append("backtest_health_missing")

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

        new["backtest_gate_active"] = gate_active
        new["backtest_profit_factor"] = profit_factor
        new["backtest_avg_return_pct"] = avg_return
        new["backtest_target_hit_rate_pct"] = target_hit
        new["backtest_stop_hit_rate_pct"] = stop_hit

        if gate_active:
            original_status = new.get("score_status") or new.get("operator_status")
            new["score_status_before_backtest_gate"] = original_status
            new["operator_status_before_backtest_gate"] = new.get("operator_status")
            new["score_status"] = "WATCH_ONLY"
            new["operator_status"] = "BACKTEST_GATE_ACTIVE"
            new["trade_gate"] = "Blocked"
            new["trade_gate_reasons"] = list(dict.fromkeys(
                list(new.get("trade_gate_reasons") or []) + blockers
            ))
            new["alert_eligible"] = False
            new["buy_setup_alert_blocked"] = True
            new["paper_order_allowed"] = False
            new["live_order_allowed"] = False
            gated_count += 1

        new["order_submission"] = False
        new["live_trading"] = False
        gated_rows.append(new)

    status = "PASS"
    if gate_active:
        status = "WARN"
        warnings.append("backtest_gate_active_trade_eligibility_blocked")

    health = {
        "schema_version": "backtest_gate_health_v1",
        "generated_at": generated_at,
        "status": status,
        "gate_active": gate_active,
        "blockers": blockers,
        "warnings": warnings,
        "rows": len(rows),
        "gated_rows": gated_count,
        "profit_factor": profit_factor,
        "target_hit_rate_pct": target_hit,
        "stop_hit_rate_pct": stop_hit,
        "avg_return_pct": avg_return,
        "operator_health_status": operator_health.get("status"),
        "order_submission": False,
        "live_trading": False,
        "message": (
            "Backtest gate blocks trade eligibility when historical evidence is weak. "
            "Rows remain visible as watch-only research signals."
        ),
    }

    output = {
        "schema_version": "operator_dashboard_backtest_gated_v1",
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
