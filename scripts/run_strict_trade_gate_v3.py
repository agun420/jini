from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prediction_engine.trade_gate.strict_trade_gate_v3 import StrictTradeGateV3


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

FINAL_V3 = DOCS / "final_trade_score_v3.json"

OUT_DOCS = DOCS / "strict_trade_gate_v3.json"
OUT_HEALTH = DOCS / "strict_trade_gate_v3_health.json"
OUT_STATE = STATE / "strict_trade_gate_v3.json"


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


def main() -> None:
    generated_at = now()
    payload = read_json(FINAL_V3, {})
    rows = rows_from(payload)

    gate = StrictTradeGateV3()
    gated = gate.evaluate(rows)

    blockers: list[str] = []
    warnings: list[str] = []

    if not rows:
        blockers.append("no_final_score_v3_rows_available")

    ready_strong = [r for r in gated if r.get("trade_gate_status_v3") == "BUY_ORDER_ALERT_READY_STRONG"]
    ready = [r for r in gated if r.get("trade_gate_status_v3") == "BUY_ORDER_ALERT_READY"]
    blocked = [r for r in gated if r.get("trade_gate_status_v3") == "BUY_ORDER_ALERT_BLOCKED"]

    if not ready_strong and not ready:
        warnings.append("no_buy_order_alert_ready_rows_currently")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "strict_trade_gate_v3_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "rows_in": len(rows),
        "rows_out": len(gated),
        "buy_order_alert_ready_strong": len(ready_strong),
        "buy_order_alert_ready": len(ready),
        "buy_order_alert_blocked": len(blocked),
        "top_ticker": gated[0].get("ticker") if gated else None,
        "top_final_trade_score_v3": gated[0].get("final_trade_score_v3") if gated else None,
        "trade_eligibility_enabled": False,
        "paper_order_allowed": False,
        "live_order_allowed": False,
        "order_submission": False,
        "live_trading": False,
    }

    out = {
        "schema_version": "strict_trade_gate_v3_v1",
        "generated_at": generated_at,
        "health": health,
        "rows": gated,
        "safety": {
            "trade_eligibility_enabled": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
            "order_submission": False,
            "live_trading": False,
            "purpose": "Research-only strict trade gate for buy-order-alert candidates.",
        },
    }

    write_json(OUT_DOCS, out)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, out)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
