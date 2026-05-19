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

OUT_RESULTS = DOCS / "backtest_results.json"
OUT_HEALTH = DOCS / "backtest_health.json"
OUT_STATE = STATE / "backtest_results.json"


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


def get_candidate_symbols(limit: int = 25) -> list[str]:
    payload = read_json(OPERATOR_DASHBOARD, {})
    rows = rows_from(payload)

    # Prefer rows with scores and prices.
    clean = []
    for row in rows:
        t = ticker(row)
        p = price(row)
        score = f(row.get("final_trade_score"))
        if t and p is not None and score is not None:
            clean.append((score, t))

    clean.sort(reverse=True)
    symbols = []
    for _, sym in clean:
        if sym not in symbols:
            symbols.append(sym)
        if len(symbols) >= limit:
            break

    return symbols


def test_symbol_with_alpaca(symbol: str, days: int, target_pct: float, stop_pct: float) -> dict[str, Any]:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from alpaca.data.enums import DataFeed

    key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
    secret = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")

    if not key or not secret:
        return {
            "symbol": symbol,
            "status": "FAIL",
            "reason": "missing_alpaca_key_or_secret",
        }

    feed_name = str(os.getenv("ALPACA_DATA_FEED") or "iex").upper()
    feed = DataFeed.SIP if feed_name == "SIP" else DataFeed.IEX

    client = StockHistoricalDataClient(key, secret)

    end = datetime.now(timezone.utc) - timedelta(minutes=20)
    start = end - timedelta(days=days)

    try:
        bars = client.get_stock_bars(
            StockBarsRequest(
                symbol_or_symbols=[symbol],
                timeframe=TimeFrame.Minute,
                start=start,
                end=end,
                feed=feed,
            )
        )

        rows = list(bars.data.get(symbol, []))
    except Exception as exc:
        return {
            "symbol": symbol,
            "status": "FAIL",
            "reason": "alpaca_bars_failed",
            "error": str(exc)[:400],
        }

    if len(rows) < 60:
        return {
            "symbol": symbol,
            "status": "SKIP",
            "reason": "not_enough_bars",
            "bars": len(rows),
        }

    # Simple walk-forward style test:
    # Enter on each bar open, then check next 30 minutes for target or stop.
    horizon = 30
    wins = 0
    losses = 0
    flats = 0
    returns: list[float] = []

    max_tests = 250
    tested = 0

    for i in range(0, max(0, len(rows) - horizon - 1), max(1, (len(rows) // max_tests))):
        entry = float(rows[i].close)
        if entry <= 0:
            continue

        target = entry * (1 + target_pct / 100)
        stop = entry * (1 - stop_pct / 100)

        outcome = "flat"
        ret = 0.0

        for j in range(i + 1, min(i + horizon + 1, len(rows))):
            hi = float(rows[j].high)
            lo = float(rows[j].low)
            close = float(rows[j].close)

            # Conservative: if both hit in same candle, assume stop first.
            if lo <= stop:
                outcome = "loss"
                ret = -stop_pct
                break
            if hi >= target:
                outcome = "win"
                ret = target_pct
                break

            if j == min(i + horizon, len(rows) - 1):
                ret = ((close - entry) / entry) * 100

        if outcome == "win":
            wins += 1
        elif outcome == "loss":
            losses += 1
        else:
            flats += 1

        returns.append(ret)
        tested += 1

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

    total = wins + losses + flats
    return {
        "symbol": symbol,
        "status": "PASS",
        "feed": feed_name,
        "bars": len(rows),
        "tests": total,
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "target_pct": target_pct,
        "stop_pct": stop_pct,
        "horizon_minutes": horizon,
        "target_hit_rate_pct": round((wins / total) * 100, 2) if total else 0,
        "stop_hit_rate_pct": round((losses / total) * 100, 2) if total else 0,
        "avg_return_pct": round(avg_return, 4),
        "profit_factor": round(profit_factor, 4),
        "max_drawdown_pct_points": round(max_dd, 4),
    }


def main() -> None:
    generated_at = now()

    symbols = get_candidate_symbols(limit=25)
    target_pct = float(os.getenv("BACKTEST_TARGET_PCT", "1.5"))
    stop_pct = float(os.getenv("BACKTEST_STOP_PCT", "0.8"))
    days = int(os.getenv("BACKTEST_DAYS", "5"))

    results = []
    blockers: list[str] = []
    warnings: list[str] = []

    if not symbols:
        blockers.append("no_candidate_symbols")
    else:
        for sym in symbols:
            results.append(test_symbol_with_alpaca(sym, days, target_pct, stop_pct))

    passed = [r for r in results if r.get("status") == "PASS"]
    failed = [r for r in results if r.get("status") == "FAIL"]
    skipped = [r for r in results if r.get("status") == "SKIP"]

    total_tests = sum(int(r.get("tests") or 0) for r in passed)
    total_wins = sum(int(r.get("wins") or 0) for r in passed)
    total_losses = sum(int(r.get("losses") or 0) for r in passed)
    total_flats = sum(int(r.get("flats") or 0) for r in passed)

    weighted_avg_return = 0.0
    if total_tests:
        weighted_avg_return = sum((float(r.get("avg_return_pct") or 0) * int(r.get("tests") or 0)) for r in passed) / total_tests

    gross_win_proxy = total_wins * target_pct
    gross_loss_proxy = total_losses * stop_pct
    portfolio_pf = gross_win_proxy / gross_loss_proxy if gross_loss_proxy > 0 else (999 if gross_win_proxy > 0 else 0)

    if not passed:
        blockers.append("no_symbols_backtested")
    if failed:
        warnings.append("some_symbols_failed")
    if skipped:
        warnings.append("some_symbols_skipped")
    if total_tests < 100:
        warnings.append("low_backtest_sample_size")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    summary = {
        "schema_version": "backtest_results_v1",
        "generated_at": generated_at,
        "status": status,
        "symbols_requested": symbols,
        "symbols_tested": len(passed),
        "symbols_failed": len(failed),
        "symbols_skipped": len(skipped),
        "total_tests": total_tests,
        "wins": total_wins,
        "losses": total_losses,
        "flats": total_flats,
        "target_pct": target_pct,
        "stop_pct": stop_pct,
        "days": days,
        "target_hit_rate_pct": round((total_wins / total_tests) * 100, 2) if total_tests else 0,
        "stop_hit_rate_pct": round((total_losses / total_tests) * 100, 2) if total_tests else 0,
        "avg_return_pct": round(weighted_avg_return, 4),
        "profit_factor": round(portfolio_pf, 4),
        "blockers": blockers,
        "warnings": warnings,
        "results": results,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "purpose": "Historical validation only. Does not submit orders.",
        },
    }

    health = {
        "schema_version": "backtest_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "symbols_tested": len(passed),
        "symbols_failed": len(failed),
        "symbols_skipped": len(skipped),
        "total_tests": total_tests,
        "target_hit_rate_pct": summary["target_hit_rate_pct"],
        "stop_hit_rate_pct": summary["stop_hit_rate_pct"],
        "avg_return_pct": summary["avg_return_pct"],
        "profit_factor": summary["profit_factor"],
        "order_submission": False,
        "live_trading": False,
    }

    write_json(OUT_RESULTS, summary)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, summary)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
