from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prediction_engine.scanners.top_gainers import TopGainerOpportunityScanner


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

# Use existing runtime outputs as source for v1.
BUY_ALERT_MODE = DOCS / "buy_order_alert_mode.json"
OPERATOR_DASH = DOCS / "operator_dashboard.json"
SCORE_V2_DASH = DOCS / "signal_dashboard_score_v2.json"
V3_ENRICHED = DOCS / "v3_enriched_rows.json"

OUT_DOCS = DOCS / "opportunities.json"
OUT_HEALTH = DOCS / "opportunities_health.json"
OUT_STATE = STATE / "opportunities.json"


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
        ("v3_enriched_rows", V3_ENRICHED),
        ("buy_order_alert_mode", BUY_ALERT_MODE),
        ("operator_dashboard", OPERATOR_DASH),
        ("score_v2_dashboard", SCORE_V2_DASH),
    ]:
        payload = read_json(path, {})
        rows = rows_from(payload)
        if rows:
            return name, rows
    return "none", []


def main() -> None:
    generated_at = now()
    source_name, rows = first_rows()

    scanner = TopGainerOpportunityScanner()
    opportunities = scanner.scan(rows, limit=100)

    blockers: list[str] = []
    warnings: list[str] = []

    if not rows:
        blockers.append("no_source_rows_available")

    candidates = [r for r in opportunities if r.get("scanner_status") == "OPPORTUNITY_CANDIDATE"]
    blocked = [r for r in opportunities if r.get("scanner_status") == "BLOCKED_BY_SCANNER"]

    if not candidates:
        warnings.append("no_opportunity_candidates_currently")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "opportunities_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "source": source_name,
        "rows_in": len(rows),
        "opportunities_out": len(opportunities),
        "opportunity_candidates": len(candidates),
        "blocked_by_scanner": len(blocked),
        "top_ticker": opportunities[0].get("ticker") if opportunities else None,
        "top_score": opportunities[0].get("opportunity_score") if opportunities else None,
        "order_submission": False,
        "live_trading": False,
        "paper_order_allowed": False,
        "live_order_allowed": False,
    }

    payload = {
        "schema_version": "opportunities_v1",
        "generated_at": generated_at,
        "health": health,
        "rows": opportunities,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
            "purpose": "Research-only opportunity scanner.",
        },
    }

    write_json(OUT_DOCS, payload)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, payload)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
