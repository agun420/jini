from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prediction_engine.features.feature_builder import FeatureBuilder


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

OPPORTUNITIES = DOCS / "opportunities.json"
BUY_ALERT_MODE = DOCS / "buy_order_alert_mode.json"
OPERATOR_DASH = DOCS / "operator_dashboard.json"

OUT_DOCS = DOCS / "features_snapshot.json"
OUT_HEALTH = DOCS / "features_snapshot_health.json"
OUT_STATE = STATE / "features_snapshot.json"


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
        ("opportunities", OPPORTUNITIES),
        ("buy_order_alert_mode", BUY_ALERT_MODE),
        ("operator_dashboard", OPERATOR_DASH),
    ]:
        payload = read_json(path, {})
        rows = rows_from(payload)
        if rows:
            return name, rows
    return "none", []


def main() -> None:
    generated_at = now()
    source, rows = first_rows()

    builder = FeatureBuilder()
    features = builder.build(rows)

    blockers: list[str] = []
    warnings: list[str] = []

    if not rows:
        blockers.append("no_source_rows_available")

    passed = [r for r in features if r.get("feature_quality_pass") is True]
    failed = [r for r in features if r.get("feature_quality_pass") is False]

    spread_missing = [r for r in features if "spread_missing" in r.get("feature_warnings", [])]
    source_unknown = [r for r in features if "source_unknown" in r.get("feature_warnings", [])]

    if failed:
        warnings.append("some_feature_rows_failed_quality")

    if spread_missing:
        warnings.append("some_feature_rows_missing_spread")

    if source_unknown:
        warnings.append("some_feature_rows_unknown_source")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "features_snapshot_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "source": source,
        "rows_in": len(rows),
        "features_out": len(features),
        "feature_quality_pass": len(passed),
        "feature_quality_fail": len(failed),
        "spread_missing_rows": len(spread_missing),
        "source_unknown_rows": len(source_unknown),
        "top_ticker": features[0].get("ticker") if features else None,
        "order_submission": False,
        "live_trading": False,
        "paper_order_allowed": False,
        "live_order_allowed": False,
    }

    payload = {
        "schema_version": "features_snapshot_v1",
        "generated_at": generated_at,
        "health": health,
        "rows": features,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
            "purpose": "Research-only feature builder snapshot.",
        },
    }

    write_json(OUT_DOCS, payload)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, payload)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
