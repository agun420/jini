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

OUT_RESULTS = DOCS / "score_v2_backtest.json"
OUT_HEALTH = DOCS / "score_v2_backtest_health.json"
OUT_STATE = STATE / "score_v2_backtest.json"


TARGET_PCT = float(os.getenv("SCORE_V2_BACKTEST_TARGET_PCT", "0.6"))
STOP_PCT = float(os.getenv("SCORE_V2_BACKTEST_STOP_PCT", "1.0"))
HORIZON_MINUTES = int(os.getenv("SCORE_V2_BACKTEST_HORIZON", "15"))
DAYS = int(os.getenv("SCORE_V2_BACKTEST_DAYS", "5"))


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


def candidate_symbols(limit: int = 25) -> tuple[list[str], list[dict[str, Any]]]:
    payload = read_json(SCORE_V2_DASH, {})
    rows = rows_from(payload)

    clean = []
    for row in rows:
        t = ticker(row)
        p = price(row)
        sv2 = f(row.get("score_v2"))
        if t and p is not None and sv2 is not None:
            clean.append(dict(row))

    clean.sort(key=lambda r: f(r.get("score_v2")) or -999, reverse=True)

    symbols = []
    selected = []
    for row in clean:
        sym = ticker(row)
        if sym not in symbols:
            symbols.append(sym)
            selected.append(row)
        if len(symbols) >= limit:
            break

    return symbols, selected


def fetch_bars(symbols: list[str]) -> dict[str, list[Any]]:
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
    start = end - timedelta(days=DAYS)

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


def test_symbol(symbol: str, bars: list[Any]) -> dict[str, Any]:
    if len(bars) < HORIZON_MINUTES + 60:
        return {
            "symbol": symbol,
            "status": "SKIP",
            "reason": "not_enough_bars",
            "bars": len(bars),
        }

    wins = 0
    losses = 0
    flats = 0
    returns: list[float] = []

    step = max(1, len(bars) // 300)

    for i in range(0, max(0, len(bars) - HORIZON_MINUTES - 1), step):
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
                ret = ((close - entry) / entry) * 100

        if outcome == "win":
            wins += 1
        elif outcome == "loss":
            losses += 1
        else:
            flats += 1

        returns.append(ret)

    tests = wins + losses + flats
    gross_wins = sum(x for x in returns if x > 0)
    gross_losses = abs(sum(x for x in returns if x < 0))
    pf = gross_wins / gross_losses if gross_losses > 0 else (999 if gross_wins > 0 else 0)
    avg = sum(returns) / len(returns) if returns else 0

    return {
        "symbol": symbol,
        "status": "PASS",
        "bars": len(bars),
        "tests": tests,
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "target_hit_rate_pct": round((wins / tests) * 100, 2) if tests else 0,
        "stop_hit_rate_pct": round((losses / tests) * 100, 2) if tests else 0,
        "avg_return_pct": round(avg, 5),
        "profit_factor": round(pf, 5),
    }


def main() -> None:
    generated_at = now()

    symbols, selected_rows = candidate_symbols(limit=25)

    blockers: list[str] = []
    warnings: list[str] = []

    if not symbols:
        blockers.append("no_score_v2_symbols")

    results = []
    all_bars = {}

    if symbols:
        try:
            all_bars = fetch_bars(symbols)
        except Exception as exc:
            blockers.append("alpaca_bars_fetch_failed")
            warnings.append(str(exc)[:300])

    for sym in symbols:
        results.append(test_symbol(sym, all_bars.get(sym, [])))

    passed = [r for r in results if r.get("status") == "PASS"]
    failed = [r for r in results if r.get("status") == "FAIL"]
    skipped = [r for r in results if r.get("status") == "SKIP"]

    total_tests = sum(int(r.get("tests") or 0) for r in passed)
    wins = sum(int(r.get("wins") or 0) for r in passed)
    losses = sum(int(r.get("losses") or 0) for r in passed)
    flats = sum(int(r.get("flats") or 0) for r in passed)

    weighted_avg = sum((float(r.get("avg_return_pct") or 0) * int(r.get("tests") or 0)) for r in passed) / total_tests if total_tests else 0
    proxy_pf = (wins * TARGET_PCT) / (losses * STOP_PCT) if losses else (999 if wins else 0)

    if not passed:
        blockers.append("no_score_v2_symbols_backtested")
    if failed:
        warnings.append("some_symbols_failed")
    if skipped:
        warnings.append("some_symbols_skipped")
    if total_tests < 1000:
        warnings.append("low_sample_size")
    if proxy_pf < 1:
        warnings.append("score_v2_profit_factor_below_1")
    if weighted_avg < 0:
        warnings.append("score_v2_avg_return_negative")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    payload = {
        "schema_version": "score_v2_backtest_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "target_pct": TARGET_PCT,
        "stop_pct": STOP_PCT,
        "horizon_minutes": HORIZON_MINUTES,
        "days": DAYS,
        "selected_symbols": symbols,
        "selected_rows": selected_rows,
        "symbols_tested": len(passed),
        "symbols_failed": len(failed),
        "symbols_skipped": len(skipped),
        "total_tests": total_tests,
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "target_hit_rate_pct": round((wins / total_tests) * 100, 2) if total_tests else 0,
        "stop_hit_rate_pct": round((losses / total_tests) * 100, 2) if total_tests else 0,
        "avg_return_pct": round(weighted_avg, 5),
        "profit_factor": round(proxy_pf, 5),
        "results": results,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "purpose": "Score v2 backtest only. Does not submit orders.",
        },
    }

    health = {
        "schema_version": "score_v2_backtest_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "symbols_tested": len(passed),
        "symbols_failed": len(failed),
        "symbols_skipped": len(skipped),
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
