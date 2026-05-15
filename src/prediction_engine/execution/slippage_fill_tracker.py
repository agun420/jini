from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


PAPER_PLAN_PATH = Path("docs/data/prediction_engine/paper_order_plan.json")
PREVIOUS_TRACKER_PATH = Path("state/prediction_engine/slippage_fill_tracker.json")

OUTPUT_DOCS_PATH = Path("docs/data/prediction_engine/slippage_fill_tracker.json")
OUTPUT_STATE_PATH = Path("state/prediction_engine/slippage_fill_tracker.json")
HEALTH_PATH = Path("docs/data/prediction_engine/slippage_fill_tracker_health.json")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return json.loads(raw) if raw else default
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def build_tracker() -> Dict[str, Any]:
    plan = read_json(PAPER_PLAN_PATH, {})
    previous = read_json(PREVIOUS_TRACKER_PATH, {})
    rows = previous.get("rows") if isinstance(previous.get("rows"), list) else []

    order_plan = plan.get("order_plan") if isinstance(plan.get("order_plan"), dict) else {}
    submission = plan.get("submission") if isinstance(plan.get("submission"), dict) else {}
    selected = plan.get("selected_candidate") if isinstance(plan.get("selected_candidate"), dict) else {}

    order = order_plan.get("order") if isinstance(order_plan.get("order"), dict) else {}

    planned_entry = safe_float(order.get("estimated_entry") or selected.get("entry") or selected.get("price"))
    planned_notional = safe_float(order.get("estimated_notional"))
    symbol = order.get("symbol") or selected.get("ticker")

    actual_fill_price = None
    actual_qty = None
    order_id = None
    status = "PLAN_ONLY"

    response = submission.get("response") if isinstance(submission.get("response"), dict) else {}
    if response:
        order_id = response.get("id")
        actual_fill_price = safe_float(response.get("filled_avg_price"))
        actual_qty = safe_float(response.get("filled_qty"))
        status = response.get("status") or "SUBMITTED"

    slippage_pct = None
    if planned_entry and actual_fill_price:
        slippage_pct = (actual_fill_price - planned_entry) / planned_entry * 100

    if order_plan.get("created"):
        record_id = f"{symbol}:{plan.get('generated_at')}:{order_id or 'plan'}"
        existing_ids = {row.get("record_id") for row in rows if isinstance(row, dict)}
        if record_id not in existing_ids:
            rows.append({
                "record_id": record_id,
                "generated_at": now_utc_iso(),
                "symbol": symbol,
                "status": status,
                "order_id": order_id,
                "planned_entry": planned_entry,
                "actual_fill_price": actual_fill_price,
                "planned_notional": planned_notional,
                "actual_qty": actual_qty,
                "entry_slippage_pct": round(slippage_pct, 4) if slippage_pct is not None else None,
                "submitted": bool(submission.get("submitted")),
                "submission_reason": submission.get("reason"),
            })

    filled = [row for row in rows if row.get("actual_fill_price") is not None and row.get("planned_entry") is not None]
    slippages = [safe_float(row.get("entry_slippage_pct")) for row in filled]
    slippages = [x for x in slippages if x is not None]

    avg_slippage = sum(slippages) / len(slippages) if slippages else None

    payload = {
        "schema_version": "slippage_fill_tracker_v1",
        "generated_at": now_utc_iso(),
        "status": "PASS",
        "summary": {
            "records": len(rows),
            "filled_records": len(filled),
            "average_entry_slippage_pct": round(avg_slippage, 4) if avg_slippage is not None else None,
            "slippage_observation_count": len(slippages),
        },
        "rows": rows[-500:],
        "safety": {
            "order_submission": False,
            "tracker_only": True,
            "disclaimer": "Fill tracker only. Not financial advice.",
        },
    }
    return payload


def export_tracker() -> Dict[str, Any]:
    payload = build_tracker()
    health = {
        "schema_version": "slippage_fill_tracker_health_v1",
        "generated_at": payload["generated_at"],
        "status": payload["status"],
        "records": payload["summary"]["records"],
        "filled_records": payload["summary"]["filled_records"],
        "average_entry_slippage_pct": payload["summary"]["average_entry_slippage_pct"],
        "order_submission": False,
    }
    write_json(OUTPUT_DOCS_PATH, payload)
    write_json(OUTPUT_STATE_PATH, payload)
    write_json(HEALTH_PATH, health)
    return {
        "status": "PASS",
        "records": payload["summary"]["records"],
        "filled_records": payload["summary"]["filled_records"],
        "output_path": str(OUTPUT_DOCS_PATH),
        "health_path": str(HEALTH_PATH),
    }


def main() -> None:
    print(json.dumps(export_tracker(), indent=2))


if __name__ == "__main__":
    main()
