from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS_DIR = Path("docs/data/prediction_engine")
STATE_DIR = Path("state/prediction_engine")

PRICE_SOURCES = [
    DOCS_DIR / "signal_dashboard_safe_mode.json",
    DOCS_DIR / "signal_dashboard_stable.json",
    DOCS_DIR / "signal_dashboard_data_guard_enriched.json",
    DOCS_DIR / "signal_dashboard.json",
]

SCORE_SOURCES = [
    DOCS_DIR / "signal_dashboard_scored.json",
    DOCS_DIR / "signal_dashboard_rvol_enriched.json",
    DOCS_DIR / "signal_dashboard_second_leg_enriched.json",
    DOCS_DIR / "signal_dashboard_quality_enriched.json",
    DOCS_DIR / "signal_dashboard_finra_enriched.json",
]

OUT_DASH = DOCS_DIR / "signal_dashboard_operator.json"
OUT_HEALTH = DOCS_DIR / "operator_signal_resolver_health.json"
OUT_STATE = STATE_DIR / "operator_signal_resolver.json"


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


def ticker(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def price(row: dict[str, Any]) -> float | None:
    for key in ("price", "last_price", "close", "last", "mark"):
        v = num(row.get(key))
        if v is not None and v > 0:
            return v
    return None


def collect_by_ticker(paths: list[Path]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}

    for path in paths:
        payload = read_json(path, {})
        for row in rows_from(payload):
            t = ticker(row)
            if not t:
                continue
            existing = out.get(t, {})
            merged = {**existing, **row}
            merged["_operator_sources"] = list(dict.fromkeys(
                list(existing.get("_operator_sources", [])) + [str(path)]
            ))
            out[t] = merged

    return out


def export() -> dict[str, Any]:
    generated_at = now()

    price_rows = collect_by_ticker(PRICE_SOURCES)
    score_rows = collect_by_ticker(SCORE_SOURCES)

    all_tickers = sorted(set(price_rows) | set(score_rows))

    rows: list[dict[str, Any]] = []
    rows_with_price = 0
    rows_with_score = 0
    auth_fail_rows = 0

    for t in all_tickers:
        p_row = price_rows.get(t, {})
        s_row = score_rows.get(t, {})

        # Score row first, then price row, then force best valid price back in.
        merged = {**s_row, **p_row}
        merged["ticker"] = t

        best_price = price(p_row) or price(s_row)
        if best_price is not None:
            merged["price"] = best_price
            rows_with_price += 1

        score_keys = [
            "final_trade_score",
            "runner_potential_score",
            "entry_quality_score",
            "danger_score",
        ]
        if any(num(merged.get(k)) is not None for k in score_keys):
            rows_with_score += 1

        if merged.get("auth_safe_mode") is True or merged.get("score_status") == "ALPACA_AUTH_FAIL":
            auth_fail_rows += 1

        if not merged.get("score_status"):
            if merged.get("scanner_data_status"):
                merged["score_status"] = merged.get("scanner_data_status")
            elif best_price is not None:
                merged["score_status"] = "WATCH_ONLY"
            else:
                merged["score_status"] = "DATA_FEED_FAIL"

        merged["operator_signal_ready"] = bool(best_price is not None)
        merged["operator_score_ready"] = any(num(merged.get(k)) is not None for k in score_keys)

        rows.append(merged)

    rows.sort(key=lambda r: (
        num(r.get("final_trade_score")) or -1,
        num(r.get("runner_potential_score")) or -1,
        price(r) or -1,
    ), reverse=True)

    blockers: list[str] = []
    warnings: list[str] = []

    if not rows:
        blockers.append("operator_rows_missing")
    if rows and rows_with_price == 0:
        blockers.append("operator_prices_missing")
    if rows and rows_with_score == 0:
        warnings.append("operator_scores_missing")
    if auth_fail_rows:
        warnings.append("auth_fail_rows_present")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "operator_signal_resolver_health_v1",
        "generated_at": generated_at,
        "status": status,
        "rows": len(rows),
        "rows_with_price": rows_with_price,
        "rows_with_score": rows_with_score,
        "auth_fail_rows": auth_fail_rows,
        "blockers": blockers,
        "warnings": warnings,
        "operator_dashboard_path": str(OUT_DASH),
        "order_submission": False,
        "live_trading": False,
    }

    output = {
        "schema_version": "signal_dashboard_operator_v1",
        "generated_at": generated_at,
        "status": status,
        "rows": rows,
        "health": health,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "purpose": "Operator display resolver only. Does not submit orders.",
        },
    }

    write_json(OUT_DASH, output)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, output)

    return {
        "status": status,
        "rows": len(rows),
        "rows_with_price": rows_with_price,
        "rows_with_score": rows_with_score,
        "blockers": blockers,
        "warnings": warnings,
        "health_path": str(OUT_HEALTH),
        "dashboard_path": str(OUT_DASH),
    }


def main() -> None:
    print(json.dumps(export(), indent=2))


if __name__ == "__main__":
    main()
