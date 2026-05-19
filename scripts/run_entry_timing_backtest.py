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

OUT_RESULTS = DOCS / "entry_timing_backtest.json"
OUT_HEALTH = DOCS / "entry_timing_backtest_health.json"
OUT_STATE = STATE / "entry_timing_backtest.json"


TARGETS = [0.6, 0.8, 1.0]
STOPS = [0.4, 0.6, 0.8]
HORIZONS = [10, 15, 20]

TIMING_RULES = [
    {
        "name": "mom3_positive",
        "mom3_min_pct": 0.05,
        "mom5_min_pct": None,
        "vol_ratio_min": None,
        "avoid_spike_pct": None,
    },
    {
        "name": "mom5_positive",
        "mom3_min_pct": None,
        "mom5_min_pct": 0.10,
        "vol_ratio_min": None,
        "avoid_spike_pct": None,
    },
    {
        "name": "mom3_mom5_confirmed",
        "mom3_min_pct": 0.05,
        "mom5_min_pct": 0.10,
        "vol_ratio_min": None,
        "avoid_spike_pct": None,
    },
    {
        "name": "mom3_volume_confirmed",
        "mom3_min_pct": 0.05,
        "mom5_min_pct": None,
        "vol_ratio_min": 1.20,
        "avoid_spike_pct": None,
    },
    {
        "name": "mom3_mom5_volume_confirmed",
        "mom3_min_pct": 0.05,
        "mom5_min_pct": 0.10,
        "vol_ratio_min": 1.20,
        "avoid_spike_pct": None,
    },
    {
        "name": "confirmed_no_chase",
        "mom3_min_pct": 0.05,
        "mom5_min_pct": 0.10,
        "vol_ratio_min": 1.20,
        "avoid_spike_pct": 2.00,
    },
]


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


def candidate_symbols(limit: int = 25) -> list[str]:
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


def pct(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return ((a - b) / b) * 100


def avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def passes_timing(bars: list[Any], i: int, rule: dict[str, Any]) -> bool:
    if i < 20:
        return False

    close_now = float(bars[i].close)
    close_3 = float(bars[i - 3].close)
    close_5 = float(bars[i - 5].close)
    close_1 = float(bars[i - 1].close)

    mom3 = pct(close_now, close_3)
    mom5 = pct(close_now, close_5)
    one_bar_move = abs(pct(close_now, close_1))

    if rule.get("mom3_min_pct") is not None and mom3 < float(rule["mom3_min_pct"]):
        return False

    if rule.get("mom5_min_pct") is not None and mom5 < float(rule["mom5_min_pct"]):
        return False

    if rule.get("avoid_spike_pct") is not None and one_bar_move > float(rule["avoid_spike_pct"]):
        return False

    if rule.get("vol_ratio_min") is not None:
        current_vol = float(getattr(bars[i], "volume", 0) or 0)
        prev_vols = [float(getattr(bars[j], "volume", 0) or 0) for j in range(max(0, i - 20), i)]
        baseline = avg([v for v in prev_vols if v > 0])
        if baseline <= 0:
            return False
        vol_ratio = current_vol / baseline
        if vol_ratio < float(rule["vol_ratio_min"]):
            return False

    return True


def test_combo(all_bars: dict[str, list[Any]], rule: dict[str, Any], target_pct: float, stop_pct: float, horizon: int) -> dict[str, Any]:
    wins = 0
    losses = 0
    flats = 0
    returns: list[float] = []
    symbols_tested = 0
    total_tests = 0

    for sym, bars in all_bars.items():
        if len(bars) < horizon + 80:
            continue

        sym_tests = 0
        step = max(1, len(bars) // 400)

        for i in range(20, max(20, len(bars) - horizon - 1), step):
            if not passes_timing(bars, i, rule):
                continue

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

                # Conservative: if both hit in same bar, stop first.
                if lo <= stop:
                    outcome = "loss"
                    ret = -stop_pct
                    break

                if hi >= target:
                    outcome = "win"
                    ret = target_pct
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
            total_tests += 1
            sym_tests += 1

        if sym_tests > 0:
            symbols_tested += 1

    gross_wins = sum(x for x in returns if x > 0)
    gross_losses = abs(sum(x for x in returns if x < 0))
    pf = gross_wins / gross_losses if gross_losses > 0 else (999 if gross_wins > 0 else 0)
    avg_return = avg(returns)

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in returns:
        equity += r
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)

    target_hit = (wins / total_tests) * 100 if total_tests else 0
    stop_hit = (losses / total_tests) * 100 if total_tests else 0

    selection_score = (
        pf * 55
        + avg_return * 120
        + (target_hit - stop_hit) * 0.40
        - abs(max_dd) * 0.03
    )

    if total_tests < 250:
        selection_score -= 60
    elif total_tests < 1000:
        selection_score -= 20

    return {
        "rule_name": rule["name"],
        "rule": rule,
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
        "profit_factor": round(pf, 5),
        "max_drawdown_pct_points": round(max_dd, 5),
        "selection_score": round(selection_score, 5),
    }


def main() -> None:
    generated_at = now()
    days = int(os.getenv("ENTRY_TIMING_BACKTEST_DAYS", "5"))

    blockers: list[str] = []
    warnings: list[str] = []

    symbols = candidate_symbols(limit=25)

    if not symbols:
        blockers.append("no_score_v2_candidate_symbols")
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
        for rule in TIMING_RULES:
            for target in TARGETS:
                for stop in STOPS:
                    for horizon in HORIZONS:
                        results.append(test_combo(all_bars, rule, target, stop, horizon))

    valid = [r for r in results if int(r.get("total_tests") or 0) >= 250]

    best = None
    if valid:
        best = sorted(
            valid,
            key=lambda r: (
                float(r.get("profit_factor") or 0),
                float(r.get("avg_return_pct") or -999),
                float(r.get("selection_score") or -999),
            ),
            reverse=True,
        )[0]

    if not valid:
        blockers.append("no_valid_entry_timing_results")

    if best and float(best.get("profit_factor") or 0) < 1.2:
        warnings.append("best_entry_timing_profit_factor_below_1_2")

    if best and float(best.get("avg_return_pct") or 0) < 0:
        warnings.append("best_entry_timing_avg_return_negative")

    if best and int(best.get("total_tests") or 0) < 1000:
        warnings.append("best_entry_timing_sample_below_1000")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    payload = {
        "schema_version": "entry_timing_backtest_v1",
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
        "top_10": sorted(valid, key=lambda r: float(r.get("selection_score") or -999), reverse=True)[:10],
        "all_results": results,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "purpose": "Entry timing research only. Does not submit orders.",
        },
    }

    health = {
        "schema_version": "entry_timing_backtest_health_v1",
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
