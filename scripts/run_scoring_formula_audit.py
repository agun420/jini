from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

OPERATOR_DASHBOARD = DOCS / "operator_dashboard.json"

OUT_RESULTS = DOCS / "scoring_formula_audit.json"
OUT_HEALTH = DOCS / "scoring_formula_audit_health.json"
OUT_STATE = STATE / "scoring_formula_audit.json"


FEATURES = [
    "final_trade_score",
    "runner_potential_score",
    "entry_quality_score",
    "danger_score",
    "time_slot_rvol",
    "price",
]

HORIZON_MINUTES = 15


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


def f(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        x = float(value)
        if math.isnan(x) or math.isinf(x):
            return None
        return x
    except Exception:
        return None


def ticker(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def price(row: dict[str, Any]) -> float | None:
    for key in ("price", "last_price", "close", "last", "mark"):
        x = f(row.get(key))
        if x is not None and x > 0:
            return x
    return None


def candidate_rows(limit: int = 25) -> list[dict[str, Any]]:
    payload = read_json(OPERATOR_DASHBOARD, {})
    rows = rows_from(payload)

    clean = []
    for row in rows:
        t = ticker(row)
        p = price(row)
        final = f(row.get("final_trade_score"))
        if t and p is not None and final is not None:
            row = dict(row)
            row["ticker"] = t
            row["price"] = p
            clean.append(row)

    clean.sort(key=lambda r: f(r.get("final_trade_score")) or -999, reverse=True)
    return clean[:limit]


def fetch_bars(symbols: list[str], days: int) -> dict[str, list[Any]]:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from alpaca.data.enums import DataFeed

    key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
    secret = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")

    if not key or not secret:
        raise RuntimeError("missing_alpaca_key_or_secret")

    feed_name = str(os.getenv("ALPACA_DATA_FEED") or "iex").upper()
    feed = DataFeed.SIP if feed_name == "SIP" else DataFeed.IEX

    client = StockHistoricalDataClient(key, secret)

    end = datetime.now(timezone.utc) - timedelta(minutes=20)
    start = end - timedelta(days=days)

    bars = client.get_stock_bars(
        StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Minute,
            start=start,
            end=end,
            feed=feed,
        )
    )

    return {sym: list(rows) for sym, rows in bars.data.items()}


def forward_returns_for_symbol(symbol: str, bars: list[Any], horizon: int) -> list[float]:
    returns = []

    if len(bars) < horizon + 60:
        return returns

    step = max(1, len(bars) // 300)

    for i in range(0, max(0, len(bars) - horizon - 1), step):
        entry = float(bars[i].close)
        exit_price = float(bars[min(i + horizon, len(bars) - 1)].close)

        if entry > 0:
            returns.append(((exit_price - entry) / entry) * 100)

    return returns


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def percentile_rank(values: list[float], value: float) -> float:
    if not values:
        return 0.0
    below = sum(1 for x in values if x <= value)
    return below / len(values)


def correlation(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 3 or len(xs) != len(ys):
        return 0.0

    mx = mean(xs)
    my = mean(ys)

    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))

    if dx == 0 or dy == 0:
        return 0.0

    return num / (dx * dy)


def bucket_analysis(samples: list[dict[str, Any]], feature: str) -> dict[str, Any]:
    pairs = []
    for s in samples:
        x = f(s.get(feature))
        y = f(s.get("forward_return_pct"))
        if x is not None and y is not None:
            pairs.append((x, y))

    if len(pairs) < 5:
        return {
            "feature": feature,
            "status": "INSUFFICIENT_SAMPLE",
            "sample_size": len(pairs),
        }

    values = [x for x, _ in pairs]
    ranked = []
    for x, y in pairs:
        ranked.append((percentile_rank(values, x), x, y))

    low = [y for pct, _, y in ranked if pct <= 0.33]
    mid = [y for pct, _, y in ranked if 0.33 < pct <= 0.66]
    high = [y for pct, _, y in ranked if pct > 0.66]

    xs = [x for x, _ in pairs]
    ys = [y for _, y in pairs]

    return {
        "feature": feature,
        "status": "PASS",
        "sample_size": len(pairs),
        "correlation_to_forward_return": round(correlation(xs, ys), 5),
        "low_bucket_avg_return_pct": round(mean(low), 5),
        "mid_bucket_avg_return_pct": round(mean(mid), 5),
        "high_bucket_avg_return_pct": round(mean(high), 5),
        "high_minus_low_edge_pct": round(mean(high) - mean(low), 5),
    }


def main() -> None:
    generated_at = now()
    days = int(os.getenv("SCORING_AUDIT_DAYS", "5"))

    rows = candidate_rows(limit=25)
    symbols = [ticker(r) for r in rows]

    blockers: list[str] = []
    warnings: list[str] = []

    if not rows:
        blockers.append("no_operator_rows_with_scores")

    all_bars: dict[str, list[Any]] = {}

    if symbols:
        try:
            all_bars = fetch_bars(symbols, days=days)
        except Exception as exc:
            blockers.append("alpaca_bars_fetch_failed")
            warnings.append(str(exc)[:300])

    samples = []

    for row in rows:
        sym = ticker(row)
        bars = all_bars.get(sym, [])
        returns = forward_returns_for_symbol(sym, bars, HORIZON_MINUTES)

        if not returns:
            continue

        avg_forward = mean(returns)

        sample = {
            "ticker": sym,
            "forward_return_pct": avg_forward,
            "forward_sample_count": len(returns),
        }

        for feature in FEATURES:
            if feature == "price":
                sample[feature] = price(row)
            else:
                sample[feature] = f(row.get(feature))

        samples.append(sample)

    feature_results = [bucket_analysis(samples, feature) for feature in FEATURES]

    useful_features = [
        r for r in feature_results
        if r.get("status") == "PASS"
        and f(r.get("high_minus_low_edge_pct")) is not None
        and float(r.get("high_minus_low_edge_pct")) > 0
    ]

    harmful_features = [
        r for r in feature_results
        if r.get("status") == "PASS"
        and f(r.get("high_minus_low_edge_pct")) is not None
        and float(r.get("high_minus_low_edge_pct")) < 0
    ]

    if len(samples) < 10:
        warnings.append("low_symbol_sample_size")

    if not useful_features:
        warnings.append("no_score_feature_showed_positive_high_bucket_edge")

    if harmful_features:
        warnings.append("some_features_show_negative_high_bucket_edge")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "scoring_formula_audit_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "symbols_requested": symbols,
        "symbols_analyzed": len(samples),
        "feature_count": len(feature_results),
        "useful_feature_count": len(useful_features),
        "harmful_feature_count": len(harmful_features),
        "useful_features": useful_features,
        "harmful_features": harmful_features,
        "order_submission": False,
        "live_trading": False,
    }

    payload = {
        "schema_version": "scoring_formula_audit_v1",
        "generated_at": generated_at,
        "status": status,
        "health": health,
        "samples": samples,
        "feature_results": feature_results,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "purpose": "Scoring formula research only. Does not submit orders.",
        },
    }

    write_json(OUT_RESULTS, payload)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, payload)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
