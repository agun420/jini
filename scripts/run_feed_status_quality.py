from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prediction_engine.quality.feed_status import FeedStatusEvaluator


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

BUY_ALERT_MODE = DOCS / "buy_order_alert_mode.json"
OPERATOR_DASH = DOCS / "operator_dashboard.json"

OUT_DOCS = DOCS / "feed_status.json"
OUT_HEALTH = DOCS / "feed_status_health.json"
OUT_STATE = STATE / "feed_status.json"


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

    preferred_feed = str(os.getenv("ALPACA_DATA_FEED") or "UNKNOWN").upper()

    buy_alert = read_json(BUY_ALERT_MODE, {})
    operator = read_json(OPERATOR_DASH, {})

    rows = rows_from(buy_alert)
    if not rows:
        rows = rows_from(operator)

    evaluator = FeedStatusEvaluator()
    evaluated = [evaluator.evaluate_row(row) for row in rows]

    blockers: list[str] = []
    warnings: list[str] = []

    if not rows:
        blockers.append("no_rows_available_for_feed_status")

    usable = [r for r in evaluated if r.get("can_use_for_buy_alert") is True]
    blocked = [r for r in evaluated if r.get("can_use_for_buy_alert") is False]

    missing_price = [r for r in evaluated if "missing_or_zero_price" in r.get("blockers", [])]
    stale = [r for r in evaluated if "quote_stale" in r.get("blockers", [])]
    wide_spread = [r for r in evaluated if "spread_too_wide" in r.get("blockers", [])]
    unknown_feed = [r for r in evaluated if "feed_source_unknown" in r.get("warnings", [])]

    if missing_price:
        blockers.append("missing_or_zero_price_rows_detected")

    if stale:
        warnings.append("stale_quote_rows_detected")

    if wide_spread:
        warnings.append("wide_spread_rows_detected")

    if unknown_feed:
        warnings.append("unknown_feed_source_rows_detected")

    can_allow_buy_alerts_from_data = len(blockers) == 0 and len(usable) > 0

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "feed_status_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "preferred_feed_env": preferred_feed,
        "rows_checked": len(evaluated),
        "rows_usable_for_buy_alert": len(usable),
        "rows_blocked_by_data_quality": len(blocked),
        "missing_price_rows": len(missing_price),
        "stale_quote_rows": len(stale),
        "wide_spread_rows": len(wide_spread),
        "unknown_feed_rows": len(unknown_feed),
        "can_allow_buy_alerts_from_data": can_allow_buy_alerts_from_data,
        "can_allow_paper_orders_from_data": False,
        "can_allow_live_orders_from_data": False,
        "order_submission": False,
        "live_trading": False,
    }

    payload = {
        "schema_version": "feed_status_v1",
        "generated_at": generated_at,
        "health": health,
        "rows": evaluated,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
            "purpose": "Data quality gate only. Does not submit orders.",
        },
    }

    write_json(OUT_DOCS, payload)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, payload)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
