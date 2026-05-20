from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prediction_engine.scoring.final_trade_score_v3 import FinalTradeScoreScorerV3


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

DANGER_V3 = DOCS / "danger_score_v3.json"
ENTRY_V3 = DOCS / "entry_quality_v3.json"
RUNNER_V3 = DOCS / "runner_potential_v3.json"

OUT_DOCS = DOCS / "final_trade_score_v3.json"
OUT_HEALTH = DOCS / "final_trade_score_v3_health.json"
OUT_STATE = STATE / "final_trade_score_v3.json"


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


def first_rows() -> tuple[str, list[dict[str, Any]]]:
    for name, path in [
        ("danger_score_v3", DANGER_V3),
        ("entry_quality_v3", ENTRY_V3),
        ("runner_potential_v3", RUNNER_V3),
    ]:
        payload = read_json(path, {})
        rows = rows_from(payload)
        if rows:
            return name, rows
    return "none", []


def main() -> None:
    generated_at = now()
    source, rows = first_rows()

    scorer = FinalTradeScoreScorerV3()
    scored = scorer.score(rows)

    blockers: list[str] = []
    warnings: list[str] = []

    if not rows:
        blockers.append("no_source_rows_available")

    strong = [r for r in scored if r.get("final_trade_score_status_v3") == "BUY_ALERT_READY_STRONG"]
    watch = [r for r in scored if r.get("final_trade_score_status_v3") == "BUY_ALERT_WATCH"]
    track = [r for r in scored if r.get("final_trade_score_status_v3") == "TRACK_ONLY"]
    no_edge = [r for r in scored if r.get("final_trade_score_status_v3") == "NO_EDGE"]
    blocked = [r for r in scored if r.get("final_trade_score_status_v3") == "FINAL_BLOCKED"]

    if not strong:
        warnings.append("no_strong_buy_alert_ready_rows_currently")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "final_trade_score_v3_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "source": source,
        "rows_in": len(rows),
        "rows_out": len(scored),
        "buy_alert_ready_strong": len(strong),
        "buy_alert_watch": len(watch),
        "track_only": len(track),
        "no_edge": len(no_edge),
        "final_blocked": len(blocked),
        "top_ticker": scored[0].get("ticker") if scored else None,
        "top_final_trade_score_v3": scored[0].get("final_trade_score_v3") if scored else None,
        "trade_eligibility_enabled": False,
        "paper_order_allowed": False,
        "live_order_allowed": False,
        "order_submission": False,
        "live_trading": False,
    }

    payload = {
        "schema_version": "final_trade_score_v3_v1",
        "generated_at": generated_at,
        "health": health,
        "rows": scored,
        "safety": {
            "trade_eligibility_enabled": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
            "order_submission": False,
            "live_trading": False,
            "purpose": "Research-only final trade score.",
        },
    }

    write_json(OUT_DOCS, payload)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, payload)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
