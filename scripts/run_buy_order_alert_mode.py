from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

SCORE_V2_DASH = DOCS / "signal_dashboard_score_v2.json"
PRICE_REGIME_HEALTH = DOCS / "price_regime_focused_validation_health.json"

OUT_DASH = DOCS / "buy_order_alert_mode.json"
OUT_HEALTH = DOCS / "buy_order_alert_mode_health.json"
OUT_STATE = STATE / "buy_order_alert_mode.json"


PRICE_MIN = 10.0
PRICE_MAX = 75.0
MIN_PROFIT_FACTOR = 1.2
MIN_TOTAL_TESTS = 100
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
        x = float(value)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except Exception:
        return default


def price(row: dict[str, Any]) -> float:
    for key in ("price", "last_price", "close", "last", "mark"):
        x = f(row.get(key), 0.0)
        if x > 0:
            return x
    return 0.0


def ticker(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def main() -> None:
    generated_at = now()

    score_dash = read_json(SCORE_V2_DASH, {})
    regime = read_json(PRICE_REGIME_HEALTH, {})

    rows = rows_from(score_dash)

    blockers: list[str] = []
    warnings: list[str] = []

    regime_status = regime.get("status")
    profit_factor = f(regime.get("profit_factor"))
    avg_return = f(regime.get("avg_return_pct"))
    total_tests = int(f(regime.get("total_tests")))
    order_submission = regime.get("order_submission")
    live_trading = regime.get("live_trading")

    if not rows:
        blockers.append("score_v2_rows_missing")

    if regime_status != "PASS":
        blockers.append("price_regime_validation_not_pass")

    if profit_factor < MIN_PROFIT_FACTOR:
        blockers.append("profit_factor_below_required")

    if avg_return <= MIN_AVG_RETURN:
        blockers.append("avg_return_not_positive")

    if total_tests < MIN_TOTAL_TESTS:
        blockers.append("sample_below_required")

    if order_submission is not False:
        blockers.append("regime_order_submission_not_false")

    if live_trading is not False:
        blockers.append("regime_live_trading_not_false")

    evidence_pass = not blockers

    out_rows = []
    eligible_count = 0
    blocked_count = 0

    for row in rows:
        new = dict(row)
        sym = ticker(new)
        p = price(new)
        score_v2 = f(new.get("score_v2"))

        reasons = []

        if not evidence_pass:
            reasons.extend(blockers)

        if not sym:
            reasons.append("missing_ticker")

        if p < PRICE_MIN or p > PRICE_MAX:
            reasons.append("outside_validated_price_regime")

        if score_v2 <= 0:
            reasons.append("score_v2_missing")

        eligible = len(reasons) == 0

        if eligible:
            new["buy_order_alert_status"] = "BUY_ORDER_ALERT_ELIGIBLE"
            new["buy_order_alert_eligible"] = True
            eligible_count += 1
        else:
            new["buy_order_alert_status"] = "BUY_ORDER_ALERT_BLOCKED"
            new["buy_order_alert_eligible"] = False
            new["buy_order_alert_block_reasons"] = reasons
            blocked_count += 1

        # Hard safety. Do not change this.
        new["trade_eligible"] = False
        new["paper_order_allowed"] = False
        new["live_order_allowed"] = False
        new["order_submission"] = False
        new["live_trading"] = False
        new["validated_setup"] = "price_10_to_75_reclaim_5bar_high_light"
        new["validated_target_pct"] = 0.6
        new["validated_stop_pct"] = 0.8
        new["validated_horizon_minutes"] = 30
        new["validated_profit_factor"] = profit_factor
        new["validated_avg_return_pct"] = avg_return
        new["validated_total_tests"] = total_tests

        out_rows.append(new)

    out_rows.sort(
        key=lambda r: (
            1 if r.get("buy_order_alert_eligible") else 0,
            f(r.get("score_v2")),
            price(r),
        ),
        reverse=True,
    )

    if eligible_count == 0:
        warnings.append("no_buy_order_alert_eligible_rows_currently")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "buy_order_alert_mode_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "rows": len(out_rows),
        "buy_order_alert_eligible": eligible_count,
        "buy_order_alert_blocked": blocked_count,
        "validated_price_min": PRICE_MIN,
        "validated_price_max": PRICE_MAX,
        "validated_setup": "reclaim_5bar_high_light",
        "validated_target_pct": 0.6,
        "validated_stop_pct": 0.8,
        "validated_horizon_minutes": 30,
        "validation_profit_factor": profit_factor,
        "validation_avg_return_pct": avg_return,
        "validation_total_tests": total_tests,
        "trade_eligibility_enabled": False,
        "paper_order_allowed": False,
        "live_order_allowed": False,
        "order_submission": False,
        "live_trading": False,
        "message": "Buy order alerts may be shown for validated research setup. Orders remain disabled.",
    }

    payload = {
        "schema_version": "buy_order_alert_mode_v1",
        "generated_at": generated_at,
        "status": status,
        "health": health,
        "rows": out_rows,
        "safety": {
            "buy_order_alerts_only": True,
            "trade_eligibility_enabled": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
            "order_submission": False,
            "live_trading": False,
        },
    }

    write_json(OUT_DASH, payload)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, payload)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
