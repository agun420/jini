from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prediction_engine.scoring.danger_score_v3 import DangerScoreScorerV3


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

ENTRY_V3 = DOCS / "entry_quality_v3.json"
RUNNER_V3 = DOCS / "runner_potential_v3.json"
FEATURES = DOCS / "features_snapshot.json"

OUT_DOCS = DOCS / "danger_score_v3.json"
OUT_HEALTH = DOCS / "danger_score_v3_health.json"
OUT_STATE = STATE / "danger_score_v3.json"


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
        ("entry_quality_v3", ENTRY_V3),
        ("runner_potential_v3", RUNNER_V3),
        ("features_snapshot", FEATURES),
    ]:
        payload = read_json(path, {})
        rows = rows_from(payload)
        if rows:
            return name, rows
    return "none", []


def main() -> None:
    generated_at = now()
    source, rows = first_rows()

    scorer = DangerScoreScorerV3()
    scored = scorer.score(rows)

    blockers: list[str] = []
    warnings: list[str] = []

    if not rows:
        blockers.append("no_source_rows_available")

    low = [r for r in scored if r.get("danger_status_v3") == "DANGER_LOW"]
    medium = [r for r in scored if r.get("danger_status_v3") == "DANGER_MEDIUM"]
    high = [r for r in scored if r.get("danger_status_v3") == "DANGER_HIGH"]
    blocked = [r for r in scored if r.get("danger_status_v3") == "DANGER_BLOCKED"]

    if not low:
        warnings.append("no_low_danger_rows_currently")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "danger_score_v3_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "source": source,
        "rows_in": len(rows),
        "rows_out": len(scored),
        "danger_low": len(low),
        "danger_medium": len(medium),
        "danger_high": len(high),
        "danger_blocked": len(blocked),
        "lowest_danger_ticker": scored[0].get("ticker") if scored else None,
        "lowest_danger_score_v3": scored[0].get("danger_score_v3") if scored else None,
        "order_submission": False,
        "live_trading": False,
        "paper_order_allowed": False,
        "live_order_allowed": False,
    }

    payload = {
        "schema_version": "danger_score_v3_v1",
        "generated_at": generated_at,
        "health": health,
        "rows": scored,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
            "purpose": "Research-only danger score.",
        },
    }

    write_json(OUT_DOCS, payload)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, payload)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
