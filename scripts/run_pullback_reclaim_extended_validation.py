from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

SCORE_V2_DASH = DOCS / "signal_dashboard_score_v2.json"

OUT_RESULTS = DOCS / "pullback_reclaim_extended_validation.json"
OUT_HEALTH = DOCS / "pullback_reclaim_extended_validation_health.json"
OUT_STATE = STATE / "pullback_reclaim_extended_validation.json"


SETUP = {
    "name": "reclaim_5bar_high_light",
    "momentum_lookback": 15,
    "momentum_min_pct": 0.6,
    "pullback_lookback": 7,
    "pullback_min_pct": -1.0,
    "pullback_max_pct": -0.15,
    "reclaim_lookback": 5,
    "volume_ratio_min": None,
    "avoid_spike_pct": 2.5,
}

TARGET_PCT = 0.6
STOP_PCT = 0.8
HORIZON_MINUTES = 30


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


def pct(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return ((a - b) / b) * 100


def avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def candidate_symbols(limit: int) -> list[str]:
    payload = read_json(SCORE_V2_DASH, {})
    rows = rows_from(payload)

    clean = []
    for row in rows:
        sym = ticker(row)
        p = price(row)
        sv2 = f(row.get("score_v2"))
        if sym and p is not None and sv2 is not None:
            clean.append((sv2, sym))

    clean.sort(reverse=True)

    out = []
    for _, sym in clean:
        if sym not in out:
            out.append(sym)
        if len(out) >= limit:
            break

    return out


def fetch_symbol_bars(symbol: str, days: int) -> list[Any]:
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
            symbol_or_symbols=[symbol],
            timeframe=TimeFrame.Minute,
            start=start,
            end=end,
            feed=feed,
        )
    )

    return list(bars.data.get(symbol, []))


def passes_setup(bars: list[Any], i: int) -> bool:
    momentum_lookback = int(SETUP["momentum_lookback"])
    pullback_lookback = int(SETUP["pullback_lookback"])
    reclaim_lookback = int(SETUP["reclaim_lookback"])

    need = max(momentum_lookback + pullback_lookback + 2, 40)
    if i < need:
        return False

    close_now = float(bars[i].close)
    close_prev = float(bars[i - 1].close)

    if close_now <= 0 or close_prev <= 0:
        return False

    if abs(pct(close_now, close_prev)) > float(SETUP["avoid_spike_pct"]):
        return False

    momentum_start_idx = i - pullback_lookback - momentum_lookback
    momentum_end_idx = i - pullback_lookback

    momentum_start = float(bars[momentum_start_idx].close)
    momentum_end = float(bars[momentum_end_idx].close)

    if momentum_start <= 0:
        return False

    if pct(momentum_end, momentum_start) < float(SETUP["momentum_min_pct"]):
        return False

    pullback_start = float(bars[i - pullback_lookback].close)
    pullback_low = min(float(bars[j].low) for j in range(i - pullback_lookback, i))

    if pullback_start <= 0:
        return False

    pullback_pct = pct(pullback_low, pullback_start)

    if pullback_pct < float(SETUP["pullback_min_pct"]):
        return False

    if pullback_pct > float(SETUP["pullback_max_pct"]):
        return False

    reclaim_high = max(float(bars[j].high) for j in range(i - reclaim_lookback, i))

    return close_now > reclaim_high


def test_symbol(sym: str, bars: list[Any]) -> dict[str, Any]:
    if len(bars) < 100 + HORIZON_MINUTES:
        return {
            "symbol": sym,
            "status": "SKIP",
            "reason": "not_enough_bars",
            "bars": len(bars),
        }

    wins = 0
    losses = 0
    flats = 0
    returns: list[float] = []

    # Higher step keeps VM memory/CPU safe while still increasing sample.
    step = max(1, len(bars) // 600)

    for i in range(40, max(40, len(bars) - HORIZON_MINUTES - 1), step):
        if not passes_setup(bars, i):
            continue

        entry = float(bars[i].close)
        if entry <= 0:
            continue

        target = entry * (1 + TARGET_PCT / 100)
        stop = entry * (1 - STOP_PCT / 100)
        last_index = min(i + HORIZON_MINUTES, len(bars) - 1)

        outcome = "flat"
        ret = 0.0

        for j in range(i + 1, last_index + 1):
            hi = float(bars[j].high)
            lo = float(bars[j].low)
            close = float(bars[j].close)

            if lo <= stop:
                outcome = "loss"
                ret = -STOP_PCT
                break

            if hi >= target:
                outcome = "win"
                ret = TARGET_PCT
                break

            if j == last_index:
                ret = pct(close, entry)

        if outcome == "win":
            wins += 1
        elif outcome == "loss":
            losses += 1
        else:
            flats += 1

        returns.append(ret)

    gross_wins = sum(x for x in returns if x > 0)
    gross_losses = abs(sum(x for x in returns if x < 0))
    pf = gross_wins / gross_losses if gross_losses > 0 else (999 if gross_wins > 0 else 0)
    avg_return = avg(returns)

    total = wins + losses + flats

    return {
        "symbol": sym,
        "status": "PASS",
        "bars": len(bars),
        "tests": total,
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "target_hit_rate_pct": round((wins / total) * 100, 2) if total else 0,
        "stop_hit_rate_pct": round((losses / total) * 100, 2) if total else 0,
        "avg_return_pct": round(avg_return, 5),
        "profit_factor": round(pf, 5),
    }


def main() -> None:
    generated_at = now()
    days = int(os.getenv("PULLBACK_RECLAIM_EXT_DAYS", "15"))
    symbol_limit = int(os.getenv("PULLBACK_RECLAIM_EXT_SYMBOL_LIMIT", "35"))

    blockers: list[str] = []
    warnings: list[str] = []

    symbols = candidate_symbols(limit=symbol_limit)

    if not symbols:
        blockers.append("no_score_v2_candidate_symbols")

    results = []
    failed_symbols = []

    for sym in symbols:
        try:
            bars = fetch_symbol_bars(sym, days=days)
            results.append(test_symbol(sym, bars))
        except Exception as exc:
            failed_symbols.append({"symbol": sym, "error": str(exc)[:300]})

    passed = [r for r in results if r.get("status") == "PASS"]
    skipped = [r for r in results if r.get("status") == "SKIP"]

    total_tests = sum(int(r.get("tests") or 0) for r in passed)
    wins = sum(int(r.get("wins") or 0) for r in passed)
    losses = sum(int(r.get("losses") or 0) for r in passed)
    flats = sum(int(r.get("flats") or 0) for r in passed)

    avg_return = (
        sum(float(r.get("avg_return_pct") or 0) * int(r.get("tests") or 0) for r in passed) / total_tests
        if total_tests else 0
    )

    proxy_pf = (wins * TARGET_PCT) / (losses * STOP_PCT) if losses else (999 if wins else 0)

    if not passed:
        blockers.append("no_symbols_backtested")

    if failed_symbols:
        warnings.append("some_symbols_failed")

    if skipped:
        warnings.append("some_symbols_skipped")

    if total_tests < 500:
        warnings.append("sample_below_500")

    if len(passed) < 20:
        warnings.append("symbols_tested_below_20")

    if proxy_pf < 1.2:
        warnings.append("profit_factor_below_1_2")

    if avg_return <= 0:
        warnings.append("avg_return_not_positive")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    payload = {
        "schema_version": "pullback_reclaim_extended_validation_v2_low_memory",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "setup": SETUP,
        "target_pct": TARGET_PCT,
        "stop_pct": STOP_PCT,
        "horizon_minutes": HORIZON_MINUTES,
        "days": days,
        "symbol_limit": symbol_limit,
        "symbols_requested": symbols,
        "symbols_tested": len(passed),
        "symbols_skipped": len(skipped),
        "symbols_failed": len(failed_symbols),
        "total_tests": total_tests,
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "target_hit_rate_pct": round((wins / total_tests) * 100, 2) if total_tests else 0,
        "stop_hit_rate_pct": round((losses / total_tests) * 100, 2) if total_tests else 0,
        "avg_return_pct": round(avg_return, 5),
        "profit_factor": round(proxy_pf, 5),
        "results": results,
        "failed_symbols": failed_symbols,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "purpose": "Low-memory extended pullback reclaim validation only. Does not submit orders.",
        },
    }

    health = {
        "schema_version": "pullback_reclaim_extended_validation_health_v2_low_memory",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "symbols_tested": len(passed),
        "symbols_skipped": len(skipped),
        "symbols_failed": len(failed_symbols),
        "total_tests": total_tests,
        "target_hit_rate_pct": payload["target_hit_rate_pct"],
        "stop_hit_rate_pct": payload["stop_hit_rate_pct"],
        "avg_return_pct": payload["avg_return_pct"],
        "profit_factor": payload["profit_factor"],
        "order_submission": False,
        "live_trading": False,
    }

    write_json(OUT_RESULTS, payload)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, payload)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
