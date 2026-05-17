from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


INPUTS = [
    Path("docs/data/prediction_engine/signal_dashboard_second_leg_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_scored.json"),
    Path("docs/data/prediction_engine/signal_dashboard_market_guard_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_quality_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard.json"),
]

PROFILE_PATH = Path("state/prediction_engine/volume_profile_history.json")

OUT_DASH = Path("docs/data/prediction_engine/signal_dashboard_rvol_enriched.json")
OUT_RVOL = Path("docs/data/prediction_engine/time_slot_rvol.json")
OUT_STATE = Path("state/prediction_engine/time_slot_rvol.json")
OUT_HEALTH = Path("docs/data/prediction_engine/time_slot_rvol_health.json")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def minute_bucket() -> str:
    current = datetime.now(timezone.utc)
    return f"{current.hour:02d}:{current.minute:02d}"


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


def load_rows() -> tuple[dict[str, Any], str]:
    for path in INPUTS:
        payload = read_json(path, {})
        rows = rows_from(payload)
        if rows:
            if not isinstance(payload, dict):
                payload = {"rows": rows}
            return payload, str(path)

    return {"rows": []}, "none"


def nested(row: dict[str, Any], key: str) -> Any:
    cur: Any = row

    for part in key.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)

    return cur


def pick(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = nested(row, key) if "." in key else row.get(key)
        if value is not None:
            return value

    return None


def f(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def symbol(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def load_profile() -> dict[str, Any]:
    profile = read_json(PROFILE_PATH, {})
    if not isinstance(profile, dict):
        return {}
    return profile


def save_profile(profile: dict[str, Any]) -> None:
    write_json(PROFILE_PATH, profile)


def current_volume(row: dict[str, Any]) -> float | None:
    return f(pick(row, "volume", "day_volume", "current_volume"))


def existing_rvol(row: dict[str, Any]) -> float | None:
    return f(pick(row, "time_slot_rvol", "relative_volume", "rvol"))


def estimate_rvol(row: dict[str, Any]) -> float:
    volume = current_volume(row)
    fallback = existing_rvol(row)

    if fallback is not None and fallback > 0:
        return round(fallback, 2)

    if volume is None or volume <= 0:
        return 1.0

    if volume >= 10_000_000:
        return 6.0
    if volume >= 5_000_000:
        return 4.5
    if volume >= 1_000_000:
        return 3.0
    if volume >= 500_000:
        return 2.0

    return 1.0


def historical_median(profile: dict[str, Any], ticker: str, bucket: str) -> float | None:
    values = profile.get(ticker, {}).get(bucket, [])

    clean = []
    for value in values[-20:]:
        number = f(value)
        if number is not None and number > 0:
            clean.append(number)

    if not clean:
        return None

    return float(statistics.median(clean))


def update_profile(
    profile: dict[str, Any],
    ticker: str,
    bucket: str,
    volume: float | None,
) -> None:
    if not ticker or volume is None or volume <= 0:
        return

    profile.setdefault(ticker, {})
    profile[ticker].setdefault(bucket, [])
    profile[ticker][bucket].append(volume)

    # Keep latest 30 observations per minute bucket.
    profile[ticker][bucket] = profile[ticker][bucket][-30:]


def calculate_time_slot_rvol(
    row: dict[str, Any],
    profile: dict[str, Any],
    bucket: str,
) -> dict[str, Any]:
    ticker = symbol(row)
    volume = current_volume(row)
    old_rvol = existing_rvol(row)
    median = historical_median(profile, ticker, bucket)

    method = "fallback_estimate"
    rvol = estimate_rvol(row)

    if volume is not None and median is not None and median > 0:
        rvol = round(volume / median, 2)
        method = "same_minute_profile"
    elif old_rvol is not None and old_rvol > 0:
        rvol = round(old_rvol, 2)
        method = "existing_rvol"

    return {
        "ticker": ticker,
        "minute_bucket_utc": bucket,
        "volume": volume,
        "median_volume_20d_proxy": median,
        "time_slot_rvol": rvol,
        "method": method,
    }


def export() -> dict[str, Any]:
    dashboard, source = load_rows()
    rows = rows_from(dashboard)
    profile = load_profile()
    bucket = minute_bucket()
    generated_at = now()

    enriched = []
    rvol_rows = []

    for row in rows:
        ticker = symbol(row)
        volume = current_volume(row)

        update_profile(profile, ticker, bucket, volume)
        rvol_payload = calculate_time_slot_rvol(row, profile, bucket)

        new = dict(row)
        new["time_slot_rvol"] = rvol_payload["time_slot_rvol"]
        new["time_slot_rvol_detail"] = rvol_payload

        enriched.append(new)
        rvol_rows.append(rvol_payload)

    save_profile(profile)

    enriched.sort(
        key=lambda x: (
            float(x.get("time_slot_rvol") or 0),
            float(x.get("final_trade_score") or 0),
        ),
        reverse=True,
    )

    dashboard["rows"] = enriched
    dashboard["schema_version"] = "signal_dashboard_rvol_enriched_v1"
    dashboard["time_slot_rvol_generated_at"] = generated_at
    dashboard["time_slot_rvol_source"] = source

    output = {
        "schema_version": "time_slot_rvol_v1",
        "generated_at": generated_at,
        "status": "PASS",
        "source": source,
        "minute_bucket_utc": bucket,
        "counts": {
            "rows": len(enriched),
            "same_minute_profile": sum(
                1 for row in rvol_rows if row["method"] == "same_minute_profile"
            ),
            "existing_rvol": sum(
                1 for row in rvol_rows if row["method"] == "existing_rvol"
            ),
            "fallback_estimate": sum(
                1 for row in rvol_rows if row["method"] == "fallback_estimate"
            ),
        },
        "rows": rvol_rows,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "purpose": "Time-slot RVOL enrichment only. Does not submit orders.",
        },
    }

    health = {
        "schema_version": "time_slot_rvol_health_v1",
        "generated_at": generated_at,
        "status": "PASS",
        "rows": len(enriched),
        "minute_bucket_utc": bucket,
        "methods": output["counts"],
        "order_submission": False,
        "live_trading": False,
    }

    write_json(OUT_DASH, dashboard)
    write_json(OUT_RVOL, output)
    write_json(OUT_STATE, output)
    write_json(OUT_HEALTH, health)

    return {
        "status": "PASS",
        "rows": len(enriched),
        "rvol_path": str(OUT_RVOL),
        "dashboard_path": str(OUT_DASH),
        "health_path": str(OUT_HEALTH),
    }


def main() -> None:
    print(json.dumps(export(), indent=2))


if __name__ == "__main__":
    main()