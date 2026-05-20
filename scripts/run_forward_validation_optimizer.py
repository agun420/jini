from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prediction_engine.optimization.forward_validator import ForwardValidationOptimizer


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

TRADE_JOURNAL = STATE / "trade_journal.json"

OUT_DOCS = DOCS / "forward_validation.json"
OUT_HEALTH = DOCS / "forward_validation_health.json"
OUT_STATE = STATE / "forward_validation.json"


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


def trade_records_from(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        records = payload.get("records", {})
        if isinstance(records, dict):
            return [x for x in records.values() if isinstance(x, dict)]
        if isinstance(records, list):
            return [x for x in records if isinstance(x, dict)]
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    return []


def main() -> None:
    generated_at = now()

    journal = read_json(TRADE_JOURNAL, {})
    records = trade_records_from(journal)

    optimizer = ForwardValidationOptimizer(
        current_config_path=STATE / "runner_config.json",
        suggested_config_path=STATE / "suggested_config.json",
        starting_capital=2000.0,
    )

    result = optimizer.execute_unbiased_walk_forward(records)

    closed_trades = [
        r for r in records
        if r.get("record_type") == "TRADE"
        and r.get("status") == "CLOSED"
        and r.get("outcome_pnl") is not None
    ]

    blockers = []
    warnings = []

    if len(closed_trades) < 30:
        warnings.append("closed_trade_sample_below_30")

    if result.get("status") != "PASS":
        warnings.append("no_validated_config_suggestion")

    health = {
        "schema_version": "forward_validation_health_v1",
        "generated_at": generated_at,
        "status": "PASS" if not blockers else "FAIL",
        "blockers": blockers,
        "warnings": warnings,
        "closed_trade_count": len(closed_trades),
        "forward_validation_ready": len(closed_trades) >= 30,
        "optimizer_status": result.get("status"),
        "optimizer_reason": result.get("reason"),
        "suggested_config_exported": result.get("suggested_config_exported", False),
        "auto_config_overwrite": False,
        "paper_auto_trade_ready": False,
        "auto_trade_ready": False,
        "live_trade_ready": False,
        "order_submission": False,
        "live_trading": False,
    }

    payload = {
        "schema_version": "forward_validation_v1",
        "generated_at": generated_at,
        "health": health,
        "optimizer_result": result,
        "safety": {
            "auto_config_overwrite": False,
            "order_submission": False,
            "live_trading": False,
            "purpose": "Research-only forward validation. Suggested config only.",
        },
    }

    write_json(OUT_DOCS, payload)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, payload)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
