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
STRATEGY_REPAIR = DOCS / "strategy_repair_grid_health.json"

OUT_RESULTS = DOCS / "filtered_strategy_backtest.json"
OUT_HEALTH = DOCS / "filtered_strategy_backtest_health.json"
OUT_STATE = STATE / "filtered_strategy_backtest.json"


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


def passes_filter(row: dict[str, Any], cfg: dict[str, Any]) -> bool:
    p = price(row)
    final = f(row.get("final_trade_score"))
    entry = f(row.get("entry_quality_score"))
    runner = f(row.get("runner_potential_score"))
    danger = f(row.get("danger_score"))

    if p is None or final is None or entry is None or runner is None or danger is None:
        return False

    return (
        p >= float(cfg.get("price_min", 0))
        and final >= float(cfg.get("final_min", 0))
        and entry >= float(cfg.get("entry_min", 0))
        and runner >= float(cfg.get("runner_min", 0))
        and danger <= float(cfg.get("danger_max", 999))
    )


def filtered_symbols() -> tuple[list[str], dict[str, Any], list[dict[str, Any]]]:
    operator = read_json(OPERATOR_DASHBOARD, {})
    repair = read_json(STRATEGY_REPAIR, {})

    cfg = repair.get("recommended_filter") or {}
    rows = rows_from(operator)

    selected = []
    for row in rows:
        if passes_filter(row, cfg):
            selected.append(row)

    symbols = []
    for row in selected:
        sym = ticker(row)
        if sym and sym not in symbols:
            symbols.append(sym)

    return symbols, cfg, selected


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


def test_symbol(symbol: str, bars: list[Any], target_pct: float, stop_pct: float, horizon: int) -> dict[str, Any]:
    if len(bars) < horizon + 60:
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

    for i in range(0, max(0, len(bars) - horizon - 1), step):
        entry = float(bars[i].close)
        if entry <= 0:
            continue

        target = entry * (1 + target_pct / 100)
        stop = entry * (1 - stop_pct / 100)
        last_index = min(i + horizon, len(bars) - 1)

        outcome = "flat"
        ret = 0.0

        for j in range(i + 1, last_index + 1):
            hi = float(bars[j].high)
            lo = float(bars[j].low)
            close = float(bars[j].close)

            # Conservative: if both hit same minute, assume stop first.
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

    tests = wins + losses + flats

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
        "avg_return_pct": round(avg_return, 5),
        "profit_factor": round(profit_factor, 5),
        "max_drawdown_pct_points": round(max_dd, 5),
    }


def main() -> None:
    generated_at = now()

    repair = read_json(STRATEGY_REPAIR, {})
    best_combo = repair.get("best_backtest_combo") or {}

    target_pct = float(best_combo.get("target_pct") or 1.2)
    stop_pct = float(best_combo.get("stop_pct") or 0.3)
    horizon = int(best_combo.get("horizon_minutes") or 10)
    days = int(os.getenv("FILTERED_BACKTEST_DAYS", "5"))

    symbols, cfg, selected_rows = filtered_symbols()

    blockers: list[str] = []
    warnings: list[str] = []

    if not cfg:
        blockers.append("recommended_filter_missing")
    if not symbols:
        blockers.append("no_symbols_pass_recommended_filter")

    results = []
    all_bars = {}

    if symbols:
        try:
            all_bars = fetch_bars(symbols, days=days)
        except Exception as exc:
            blockers.append("alpaca_bars_fetch_failed")
            warnings.append(str(exc)[:300])

    for sym in symbols:
        results.append(test_symbol(sym, all_bars.get(sym, []), target_pct, stop_pct, horizon))

    passed = [r for r in results if r.get("status") == "PASS"]
    total_tests = sum(int(r.get("tests") or 0) for r in passed)
    wins = sum(int(r.get("wins") or 0) for r in passed)
    losses = sum(int(r.get("losses") or 0) for r in passed)
    flats = sum(int(r.get("flats") or 0) for r in passed)

    gross_win = sum((float(r.get("avg_return_pct") or 0) * int(r.get("tests") or 0)) for r in passed if float(r.get("avg_return_pct") or 0) > 0)
    # Use proxy PF from target/stop because symbol-level avg includes flats.
    proxy_pf = (wins * target_pct) / (losses * stop_pct) if losses else (999 if wins else 0)
    weighted_avg = sum((float(r.get("avg_return_pct") or 0) * int(r.get("tests") or 0)) for r in passed) / total_tests if total_tests else 0

    if not passed:
        blockers.append("no_symbols_backtested")
    if total_tests < 250:
        warnings.append("low_sample_size")
    if len(symbols) < 3:
        warnings.append("small_symbol_count")
    if proxy_pf < 1:
        warnings.append("filtered_profit_factor_below_1")
    if weighted_avg < 0:
        warnings.append("filtered_avg_return_negative")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    payload = {
        "schema_version": "filtered_strategy_backtest_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "recommended_filter": cfg,
        "selected_symbols": symbols,
        "selected_count": len(symbols),
        "target_pct": target_pct,
        "stop_pct": stop_pct,
        "horizon_minutes": horizon,
        "days": days,
        "symbols_tested": len(passed),
        "total_tests": total_tests,
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "target_hit_rate_pct": round((wins / total_tests) * 100, 2) if total_tests else 0,
        "stop_hit_rate_pct": round((losses / total_tests) * 100, 2) if total_tests else 0,
        "avg_return_pct": round(weighted_avg, 5),
        "profit_factor": round(proxy_pf, 5),
        "results": results,
        "order_submission": False,
        "live_trading": False,
    }

    health = {
        "schema_version": "filtered_strategy_backtest_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "selected_symbols": symbols,
        "selected_count": len(symbols),
        "symbols_tested": len(passed),
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
