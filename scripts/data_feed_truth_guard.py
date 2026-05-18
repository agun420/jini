from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS_DIR = Path("docs/data/prediction_engine")
STATE_DIR = Path("state/prediction_engine")

INPUT_DASHBOARD = DOCS_DIR / "signal_dashboard_rvol_enriched.json"
INPUT_BASE = DOCS_DIR / "signal_dashboard.json"
INPUT_SCANNER_HEALTH = DOCS_DIR / "scanner_health.json"
INPUT_RUNTIME = DOCS_DIR / "runtime_heartbeat.json"

OUT_ENRICHED = DOCS_DIR / "signal_dashboard_data_guard_enriched.json"
OUT_HEALTH = DOCS_DIR / "data_feed_quality_health.json"
OUT_STATE = STATE_DIR / "data_feed_quality.json"


def now() -> str:
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


def f(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def ticker(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def get_price(row: dict[str, Any]) -> float | None:
    for key in ("price", "last_price", "close", "last", "mark"):
        value = f(row.get(key))
        if value is not None:
            return value
    return None


def classify_row(row: dict[str, Any]) -> dict[str, Any]:
    blocks: list[str] = []

    t = ticker(row)
    price = get_price(row)
    feed = row.get("feed")
    source = row.get("source")

    if not t:
        blocks.append("missing_ticker")

    if price is None:
        blocks.append("missing_price")
    elif price <= 0:
        blocks.append("zero_or_negative_price")

    if not feed:
        blocks.append("missing_feed")

    if not source:
        blocks.append("missing_source")

    quote_age = f(row.get("quote_age_seconds") or row.get("quote_age"))
    if quote_age is not None and quote_age > 900:
        blocks.append("quote_stale_over_15_min")

    valid = len(blocks) == 0

    return {
        "ticker": t,
        "valid": valid,
        "price": price,
        "blocks": blocks,
    }


def export() -> dict[str, Any]:
    generated_at = now()

    payload = read_json(INPUT_DASHBOARD, {})
    base_payload = read_json(INPUT_BASE, {})
    scanner_health = read_json(INPUT_SCANNER_HEALTH, {})
    runtime = read_json(INPUT_RUNTIME, {})

    rows = rows_from(payload)
    if not rows:
        rows = rows_from(base_payload)

    enriched: list[dict[str, Any]] = []

    valid_count = 0
    zero_price_count = 0
    missing_price_count = 0
    missing_feed_count = 0
    missing_source_count = 0
    blocked_count = 0

    for row in rows:
        check = classify_row(row)
        new = dict(row)

        new["data_feed_valid"] = check["valid"]
        new["data_feed_blocks"] = check["blocks"]
        new["data_feed_guard_status"] = "PASS" if check["valid"] else "DATA_FEED_FAIL"

        if check["valid"]:
            valid_count += 1
        else:
            blocked_count += 1
            new["score_status_original"] = new.get("score_status")
            new["score_status"] = "DATA_FEED_FAIL"
            new["trade_gate"] = "Blocked"
            new["trade_gate_reasons"] = list(dict.fromkeys(
                list(new.get("trade_gate_reasons") or []) + check["blocks"]
            ))
            new["alert_eligible"] = False
            new["buy_setup_alert_blocked"] = True

        if "zero_or_negative_price" in check["blocks"]:
            zero_price_count += 1
        if "missing_price" in check["blocks"]:
            missing_price_count += 1
        if "missing_feed" in check["blocks"]:
            missing_feed_count += 1
        if "missing_source" in check["blocks"]:
            missing_source_count += 1

        enriched.append(new)

    data_quality_status = "PASS"
    blockers: list[str] = []
    warnings: list[str] = []

    if rows and valid_count == 0:
        data_quality_status = "FAIL"
        blockers.append("all_rows_failed_data_feed_guard")

    if zero_price_count > 0:
        blockers.append("zero_price_rows_detected")

    if missing_price_count > 0:
        blockers.append("missing_price_rows_detected")

    if missing_feed_count > 0:
        warnings.append("missing_feed_metadata")

    if missing_source_count > 0:
        warnings.append("missing_source_metadata")

    scanner_status = scanner_health.get("status") if isinstance(scanner_health, dict) else None
    runtime_status = runtime.get("status") if isinstance(runtime, dict) else None

    health = {
        "schema_version": "data_feed_quality_health_v1",
        "generated_at": generated_at,
        "status": data_quality_status,
        "rows": len(rows),
        "valid_rows": valid_count,
        "blocked_rows": blocked_count,
        "zero_price_rows": zero_price_count,
        "missing_price_rows": missing_price_count,
        "missing_feed_rows": missing_feed_count,
        "missing_source_rows": missing_source_count,
        "blockers": blockers,
        "warnings": warnings,
        "scanner_status": scanner_status or "UNKNOWN",
        "runtime_status": runtime_status or "UNKNOWN",
        "dashboard_path": str(OUT_ENRICHED),
        "order_submission": False,
        "live_trading": False,
        "message": (
            "Data feed guard blocks rows with missing/zero prices so they cannot appear "
            "as normal buy/watch candidates."
        ),
    }

    output = {
        "schema_version": "signal_dashboard_data_guard_enriched_v1",
        "generated_at": generated_at,
        "status": data_quality_status,
        "rows": enriched,
        "health": health,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "purpose": "Data quality guard only. Does not submit orders.",
        },
    }

    write_json(OUT_ENRICHED, output)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, health)

    return {
        "status": data_quality_status,
        "rows": len(rows),
        "valid_rows": valid_count,
        "blocked_rows": blocked_count,
        "zero_price_rows": zero_price_count,
        "missing_price_rows": missing_price_count,
        "health_path": str(OUT_HEALTH),
        "dashboard_path": str(OUT_ENRICHED),
    }


def main() -> None:
    print(json.dumps(export(), indent=2))


if __name__ == "__main__":
    main()
