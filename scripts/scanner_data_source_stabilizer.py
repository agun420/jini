from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS_DIR = Path("docs/data/prediction_engine")
STATE_DIR = Path("state/prediction_engine")

INPUT_CURRENT = DOCS_DIR / "signal_dashboard.json"

OUT_STABLE = DOCS_DIR / "signal_dashboard_stable.json"
OUT_HEALTH = DOCS_DIR / "scanner_data_source_health.json"
OUT_CACHE = STATE_DIR / "last_good_signal_rows.json"
OUT_STATE_HEALTH = STATE_DIR / "scanner_data_source_health.json"


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
        for key in ("rows", "signals", "candidates", "items", "data"):
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


def price(row: dict[str, Any]) -> float | None:
    for key in ("price", "last_price", "close", "last", "mark"):
        value = f(row.get(key))
        if value is not None:
            return value
    return None


def row_is_good(row: dict[str, Any]) -> bool:
    t = ticker(row)
    p = price(row)
    return bool(t and p is not None and p > 0)


def cache_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        t = ticker(row)
        if t:
            out[t] = row
    return out


def stabilize_rows(current_rows: list[dict[str, Any]], cache_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cache = cache_map(cache_rows)
    stable: list[dict[str, Any]] = []

    current_good = 0
    current_bad = 0
    restored_from_cache = 0
    no_cache_available = 0

    for row in current_rows:
        t = ticker(row)
        p = price(row)
        is_good = row_is_good(row)

        if is_good:
            new = dict(row)
            new["scanner_data_status"] = "LIVE_DATA_OK"
            new["scanner_data_source_stable"] = True
            new["scanner_data_restored_from_cache"] = False
            stable.append(new)
            current_good += 1
            continue

        current_bad += 1

        cached = cache.get(t)
        if cached and row_is_good(cached):
            new = dict(cached)
            new["scanner_data_status"] = "STALE_DATA_RESTORED"
            new["scanner_data_source_stable"] = True
            new["scanner_data_restored_from_cache"] = True
            new["scanner_data_current_bad_price"] = p
            new["scanner_data_warning"] = "Current scan had invalid price. Last known good row restored."
            new["score_status_original"] = new.get("score_status")
            new["score_status"] = "STALE_DATA"
            new["alert_eligible"] = False
            new["buy_setup_alert_blocked"] = True
            stable.append(new)
            restored_from_cache += 1
        else:
            new = dict(row)
            new["scanner_data_status"] = "DATA_FEED_FAIL"
            new["scanner_data_source_stable"] = False
            new["scanner_data_restored_from_cache"] = False
            new["scanner_data_current_bad_price"] = p
            new["score_status_original"] = new.get("score_status")
            new["score_status"] = "DATA_FEED_FAIL"
            new["alert_eligible"] = False
            new["buy_setup_alert_blocked"] = True
            stable.append(new)
            no_cache_available += 1

    stats = {
        "current_rows": len(current_rows),
        "current_good_rows": current_good,
        "current_bad_rows": current_bad,
        "restored_from_cache": restored_from_cache,
        "no_cache_available": no_cache_available,
    }

    return stable, stats


def export() -> dict[str, Any]:
    generated_at = now()

    current_payload = read_json(INPUT_CURRENT, {})
    current_rows = rows_from(current_payload)

    cache_payload = read_json(OUT_CACHE, {"rows": []})
    cache_rows = rows_from(cache_payload)

    stable_rows, stats = stabilize_rows(current_rows, cache_rows)

    # Update cache only with rows that have real live prices from the current scan.
    new_good_cache = [row for row in current_rows if row_is_good(row)]
    cache_updated = False
    if new_good_cache:
        write_json(OUT_CACHE, {
            "schema_version": "last_good_signal_rows_v1",
            "generated_at": generated_at,
            "rows": new_good_cache,
            "source": str(INPUT_CURRENT),
        })
        cache_updated = True

    status = "PASS"
    blockers: list[str] = []
    warnings: list[str] = []

    if not current_rows:
        status = "FAIL"
        blockers.append("current_scanner_rows_missing")
    elif stats["current_good_rows"] == 0 and stats["restored_from_cache"] == 0:
        status = "FAIL"
        blockers.append("no_valid_current_or_cached_prices")
    elif stats["current_bad_rows"] > 0:
        status = "WARN"
        warnings.append("bad_current_rows_detected")

    if stats["restored_from_cache"] > 0:
        warnings.append("last_good_rows_restored")

    output = {
        "schema_version": "signal_dashboard_stable_v1",
        "generated_at": generated_at,
        "status": status,
        "rows": stable_rows,
        "stats": stats,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "purpose": "Stabilizes scanner rows. Does not submit orders.",
        },
    }

    health = {
        "schema_version": "scanner_data_source_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "cache_updated": cache_updated,
        "cache_path": str(OUT_CACHE),
        "stable_dashboard_path": str(OUT_STABLE),
        **stats,
        "order_submission": False,
        "live_trading": False,
    }

    write_json(OUT_STABLE, output)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE_HEALTH, health)

    return {
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        **stats,
        "cache_updated": cache_updated,
        "stable_dashboard_path": str(OUT_STABLE),
        "health_path": str(OUT_HEALTH),
    }


def main() -> None:
    print(json.dumps(export(), indent=2))


if __name__ == "__main__":
    main()
