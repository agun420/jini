from __future__ import annotations

import json
import os
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

OPERATOR_DASHBOARD = DOCS / "operator_dashboard.json"

OUT_RESULTS = DOCS / "backtest_tuning_grid.json"
OUT_HEALTH = DOCS / "backtest_tuning_grid_health.json"
OUT_STATE = STATE / "backtest_tuning_grid.json"


TARGETS = [0.4, 0.6, 0.8, 1.0, 1.2, 1.5]
STOPS = [0.3, 0.4, 0.5, 0.6, 0.8, 1.0]
HORIZONS = [10, 15, 20, 30]


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


def candidate_symbols(limit: int = 20) -> list[str]:
    payload = read_json(OPERATOR_DASHBOARD, {})
    rows = rows_from(payload)

    ranked = []
    for row in rows:
        t = ticker(row)
        p = price(row)
        score = f(row.get("final_trade_score"))
        if t and p and score is not None:
            ranked.append((score, t))

    ranked.sort(reverse=True)

    out = []
    for _, sym in ranked:
        if sym not in out:
            out.append(sym)
        if len(out) >= limit:
            break

    return out


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


def test_combo(all_bars: dict[str, list[Any]], target_pct: float, stop_pct: float, horizon: int) -> dict[str, Any]:
    wins = 0
    losses = 0
    flats = 0
    returns: list[float] = []
    symbols_tested = 0
    total_tests = 0

    for sym, bars in all_bars.items():
        if len(bars) < horizon + 60:
            continue

        symbols_tested += 1
        step = max(1, len(bars) // 250)

        for i in range(0, max(0, len(bars) - horizon - 1), step):
            entry = float(bars[i].close)
            if entry <= 0:
                continue

            target = entry * (1 + target_pct / 100)
            stop = entry * (1 - stop_pct / 100)

            outcome = "flat"
            ret = 0.0

            last_index = min(i + horizon, len(bars) - 1)

            for j in range(i + 1, last_index + 1):
                hi = float(bars[j].high)
                lo = float(bars[j].low)
                close = float(bars[j].close)

                # Conservative. If both hit same candle, assume stop first.
                if lo <= stop:
                    outcome = "loss"
                    ret = -stop_pct
                    break

                if hi >= target:
                    outcome = "win"
                    ret = target_pct
                    break

                if j == last_index:
                    ret = ((close - entry) / entry) * 100

            if outcome == "win":
                wins += 1
            elif outcome == "loss":
                losses += 1
            else:
                flats += 1

            returns.append(ret)
            total_tests += 1

    gross_wins = sum(x for x in returns if x > 0)
    gross_losses = abs(sum(x for x in returns if x < 0))
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else (999 if gross_wins > 0 else 0)
    avg_return = sum(returns) / len(returns) if returns else 0

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in returns:
        equity += r
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)

    target_hit = (wins / total_tests) * 100 if total_tests else 0
    stop_hit = (losses / total_tests) * 100 if total_tests else 0

    # Conservative selection score.
    # Penalize low sample, negative return, and weak PF.
    selection_score = (
        profit_factor * 40
        + avg_return * 20
        + (target_hit - stop_hit) * 0.5
        - abs(max_dd) * 0.05
    )

    if total_tests < 250:
        selection_score -= 25

    return {
        "target_pct": target_pct,
        "stop_pct": stop_pct,
        "horizon_minutes": horizon,
        "symbols_tested": symbols_tested,
        "total_tests": total_tests,
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "target_hit_rate_pct": round(target_hit, 2),
        "stop_hit_rate_pct": round(stop_hit, 2),
        "avg_return_pct": round(avg_return, 5),
        "profit_factor": round(profit_factor, 5),
        "max_drawdown_pct_points": round(max_dd, 5),
        "selection_score": round(selection_score, 5),
    }


def main() -> None:
    generated_at = now()
    days = int(os.getenv("BACKTEST_TUNING_DAYS", "5"))

    blockers: list[str] = []
    warnings: list[str] = []

    symbols = candidate_symbols(limit=20)

    if not symbols:
        blockers.append("no_candidate_symbols")
        all_bars = {}
    else:
        try:
            all_bars = fetch_bars(symbols, days=days)
        except Exception as exc:
            blockers.append("alpaca_bars_fetch_failed")
            all_bars = {}
            warnings.append(str(exc)[:300])

    results = []

    if all_bars:
        for target in TARGETS:
            for stop in STOPS:
                for horizon in HORIZONS:
                    results.append(test_combo(all_bars, target, stop, horizon))

    valid = [r for r in results if r["total_tests"] >= 250]

    # Best should have PF above 1 if possible. Otherwise it still tells us none work.
    best = None
    if valid:
        best = sorted(
            valid,
            key=lambda r: (
                r["profit_factor"],
                r["avg_return_pct"],
                r["selection_score"],
                -r["stop_hit_rate_pct"],
            ),
            reverse=True,
        )[0]

    if not valid:
        blockers.append("no_valid_backtest_grid_results")

    if best and best["profit_factor"] < 1:
        warnings.append("no_profitable_combo_found_profit_factor_below_1")

    if best and best["avg_return_pct"] < 0:
        warnings.append("best_combo_avg_return_negative")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    payload = {
        "schema_version": "backtest_tuning_grid_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "days": days,
        "symbols_requested": symbols,
        "symbols_with_bars": sorted(all_bars.keys()),
        "combo_count": len(results),
        "valid_combo_count": len(valid),
        "best_combo": best,
        "top_10": sorted(valid, key=lambda r: r["selection_score"], reverse=True)[:10],
        "all_results": results,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "purpose": "Backtest parameter tuning only. Does not submit orders.",
        },
    }

    health = {
        "schema_version": "backtest_tuning_grid_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "combo_count": len(results),
        "valid_combo_count": len(valid),
        "best_combo": best,
        "order_submission": False,
        "live_trading": False,
    }

    write_json(OUT_RESULTS, payload)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, payload)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
