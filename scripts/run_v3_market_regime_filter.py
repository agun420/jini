from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

ENRICHED = DOCS / "v3_enriched_rows.json"

OUT_DOCS = DOCS / "v3_market_regime_filter.json"
OUT_HEALTH = DOCS / "v3_market_regime_filter_health.json"
OUT_STATE = STATE / "v3_market_regime_filter.json"

MARKET_TICKERS = {"SPY", "QQQ", "IWM", "DIA"}


def now_iso() -> str:
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
    if isinstance(payload, dict):
        rows = payload.get("rows")
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


def f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except Exception:
        return default


def ticker(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def main() -> None:
    generated_at = now_iso()

    payload = read_json(ENRICHED, {})
    rows = rows_from(payload)

    blockers: list[str] = []
    warnings: list[str] = []

    by_ticker = {ticker(r): r for r in rows if ticker(r)}

    market_rows = []
    for sym in MARKET_TICKERS:
        r = by_ticker.get(sym)
        if r:
            market_rows.append(r)

    if not rows:
        blockers.append("no_enriched_rows")

    if not market_rows:
        warnings.append("no_market_index_rows_found_using_universe_proxy")

    # If SPY/QQQ/IWM are not in the universe, use broad row proxy.
    source_rows = market_rows if market_rows else rows

    day_moves = [f(r.get("day_move_pct")) for r in source_rows]
    vwap_dists = [f(r.get("vwap_distance_pct")) for r in source_rows]
    mom1s = [f(r.get("momentum_1m")) for r in source_rows]
    mom5s = [f(r.get("momentum_5m")) for r in source_rows]

    avg_day_move = sum(day_moves) / len(day_moves) if day_moves else 0.0
    avg_vwap_dist = sum(vwap_dists) / len(vwap_dists) if vwap_dists else 0.0
    avg_mom1 = sum(mom1s) / len(mom1s) if mom1s else 0.0
    avg_mom5 = sum(mom5s) / len(mom5s) if mom5s else 0.0

    positive_move_count = sum(1 for x in day_moves if x > 0)
    above_vwap_count = sum(1 for x in vwap_dists if x > 0)
    positive_mom_count = sum(1 for x in mom5s if x > 0)

    count = len(source_rows) or 1
    positive_move_pct = positive_move_count / count * 100
    above_vwap_pct = above_vwap_count / count * 100
    positive_mom_pct = positive_mom_count / count * 100

    regime_score = 50.0
    regime_score += avg_day_move * 6
    regime_score += avg_vwap_dist * 4
    regime_score += avg_mom5 * 8
    regime_score += (positive_move_pct - 50) * 0.20
    regime_score += (above_vwap_pct - 50) * 0.15
    regime_score += (positive_mom_pct - 50) * 0.15

    regime_score = max(0.0, min(100.0, regime_score))

    if regime_score >= 62:
        regime = "RISK_ON"
        recommendation = "Allow normal research alerting. Momentum conditions are supportive."
    elif regime_score <= 42:
        regime = "RISK_OFF"
        recommendation = "Be defensive. Keep alerts research-only and prefer stronger confirmation."
    else:
        regime = "NEUTRAL"
        recommendation = "Normal caution. Avoid weak setups and chase entries."

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "v3_market_regime_filter_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "regime": regime,
        "regime_score": round(regime_score, 4),
        "recommendation": recommendation,
        "source": "market_index_rows" if market_rows else "universe_proxy",
        "source_rows": len(source_rows),
        "avg_day_move_pct": round(avg_day_move, 4),
        "avg_vwap_distance_pct": round(avg_vwap_dist, 4),
        "avg_momentum_1m": round(avg_mom1, 4),
        "avg_momentum_5m": round(avg_mom5, 4),
        "positive_move_pct": round(positive_move_pct, 2),
        "above_vwap_pct": round(above_vwap_pct, 2),
        "positive_momentum_pct": round(positive_mom_pct, 2),
        "order_submission": False,
        "live_trading": False,
        "paper_order_allowed": False,
        "live_order_allowed": False,
    }

    out = {
        "schema_version": "v3_market_regime_filter_v1",
        "generated_at": generated_at,
        "health": health,
        "market_rows": market_rows,
        "safety": {
            "purpose": "Market regime filter for research context only. Does not trade.",
            "order_submission": False,
            "live_trading": False,
        },
    }

    write_json(OUT_DOCS, out)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, out)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
