from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prediction_engine.scoring.runner_potential_v3 import RunnerPotentialScorerV3


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

FEATURES = DOCS / "features_snapshot.json"
OPPORTUNITIES = DOCS / "opportunities.json"

OUT_DOCS = DOCS / "runner_potential_v3.json"
OUT_HEALTH = DOCS / "runner_potential_v3_health.json"
OUT_STATE = STATE / "runner_potential_v3.json"


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
        ("features_snapshot", FEATURES),
        ("opportunities", OPPORTUNITIES),
    ]:
        payload = read_json(path, {})
        rows = rows_from(payload)
        if rows:
            return name, rows
    return "none", []


def main() -> None:
    generated_at = now()
    source, rows = first_rows()

    scorer = RunnerPotentialScorerV3()
    scored = scorer.score(rows)

    blockers: list[str] = []
    warnings: list[str] = []

    if not rows:
        blockers.append("no_source_rows_available")

    strong = [r for r in scored if r.get("runner_potential_status_v3") == "RUNNER_STRONG"]
    watch = [r for r in scored if r.get("runner_potential_status_v3") == "RUNNER_WATCH"]
    weak = [r for r in scored if r.get("runner_potential_status_v3") == "RUNNER_WEAK"]
    blocked = [r for r in scored if r.get("runner_potential_status_v3") == "RUNNER_BLOCKED"]

    if not strong:
        warnings.append("no_runner_strong_rows_currently")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "runner_potential_v3_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "source": source,
        "rows_in": len(rows),
        "rows_out": len(scored),
        "runner_strong": len(strong),
        "runner_watch": len(watch),
        "runner_weak": len(weak),
        "runner_blocked": len(blocked),
        "top_ticker": scored[0].get("ticker") if scored else None,
        "top_runner_potential_v3": scored[0].get("runner_potential_v3") if scored else None,
        "order_submission": False,
        "live_trading": False,
        "paper_order_allowed": False,
        "live_order_allowed": False,
    }

    payload = {
        "schema_version": "runner_potential_v3_v1",
        "generated_at": generated_at,
        "health": health,
        "rows": scored,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
            "purpose": "Research-only runner potential score.",
        },
    }

    write_json(OUT_DOCS, payload)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, payload)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
