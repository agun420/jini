from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

SOURCE_FILES = [
    # Paid scanner output is the freshest source — loaded first so its tickers
    # take priority over legacy seed files.  Missing file is silently skipped.
    DOCS / "alpaca_paid_market_candidates.json",
    DOCS / "operator_dashboard.json",
    DOCS / "signal_dashboard_score_v2.json",
    DOCS / "buy_order_alert_mode.json",
    DOCS / "opportunities.json",
    DOCS / "v3_signal_pipeline.json",
]

# Always included so the market regime filter can find real index data.
INDEX_TICKERS = ["SPY", "QQQ", "IWM", "DIA"]

# Outcome journals used to compute per-ticker historical success rate.
PRE_JOURNAL = DOCS / "v3_prebreakout_outcome_journal.json"
REACTIVE_JOURNAL = DOCS / "v3_research_alert_outcome_journal.json"

OUT_DOCS = DOCS / "v3_enriched_rows.json"
OUT_HEALTH = DOCS / "v3_enriched_rows_health.json"
OUT_STATE = STATE / "v3_enriched_rows.json"


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
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "signals", "candidates", "items", "data", "predictions", "ready_rows", "blocked_rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        x = float(value)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except Exception:
        return default


def pct(current: float, base: float) -> float:
    if base <= 0:
        return 0.0
    return ((current - base) / base) * 100.0


def ticker(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def row_price(row: dict[str, Any]) -> float:
    for key in ("price", "last_price", "close", "last", "mark"):
        x = f(row.get(key), 0.0)
        if x > 0:
            return x
    return 0.0


def collect_seed_rows() -> list[dict[str, Any]]:
    by_symbol: dict[str, dict[str, Any]] = {}

    for path in SOURCE_FILES:
        payload = read_json(path, {})
        for row in rows_from(payload):
            sym = ticker(row)
            if not sym:
                continue

            base = by_symbol.get(sym, {"ticker": sym, "_sources": []})
            if path.name not in base["_sources"]:
                base["_sources"].append(path.name)

            for k, v in row.items():
                if k not in base or base.get(k) in [None, "", 0, 0.0, -1, -1.0]:
                    if v not in [None, ""]:
                        base[k] = v

            p = row_price(row)
            if p > 0:
                base["price"] = p

            by_symbol[sym] = base

    rows = list(by_symbol.values())
    rows.sort(key=lambda r: row_price(r), reverse=True)
    return rows[:100]


def alpaca_keys() -> tuple[str | None, str | None]:
    key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
    secret = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
    return key, secret


def enrich_with_alpaca(symbols: list[str]) -> tuple[dict[str, dict[str, Any]], list[str], list[str]]:
    warnings: list[str] = []
    blockers: list[str] = []
    enriched: dict[str, dict[str, Any]] = {}

    key, secret = alpaca_keys()
    if not key or not secret:
        blockers.append("missing_alpaca_keys")
        return enriched, warnings, blockers

    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.data.enums import DataFeed
    except Exception as exc:
        blockers.append(f"alpaca_import_failed:{str(exc)[:120]}")
        return enriched, warnings, blockers

    feed_name = str(os.getenv("ALPACA_DATA_FEED") or "IEX").upper()
    feed = DataFeed.SIP if feed_name == "SIP" else DataFeed.IEX

    client = StockHistoricalDataClient(key, secret)

    end = datetime.now(timezone.utc)
    start_intraday = end - timedelta(hours=8)
    start_daily = end - timedelta(days=10)

    quote_map = {}
    bars_map = {}
    daily_map = {}

    try:
        q = client.get_stock_latest_quote(
            StockLatestQuoteRequest(symbol_or_symbols=symbols, feed=feed)
        )
        quote_map = dict(q)
    except Exception as exc:
        warnings.append(f"latest_quote_failed:{str(exc)[:160]}")

    try:
        bars = client.get_stock_bars(
            StockBarsRequest(
                symbol_or_symbols=symbols,
                timeframe=TimeFrame.Minute,
                start=start_intraday,
                end=end,
                feed=feed,
            )
        )
        bars_map = {sym: list(vals) for sym, vals in bars.data.items()}
    except Exception as exc:
        warnings.append(f"minute_bars_failed:{str(exc)[:160]}")

    try:
        daily = client.get_stock_bars(
            StockBarsRequest(
                symbol_or_symbols=symbols,
                timeframe=TimeFrame.Day,
                start=start_daily,
                end=end,
                feed=feed,
            )
        )
        daily_map = {sym: list(vals) for sym, vals in daily.data.items()}
    except Exception as exc:
        warnings.append(f"daily_bars_failed:{str(exc)[:160]}")

    for sym in symbols:
        out: dict[str, Any] = {
            "ticker": sym,
            "alpaca_feed_used": feed_name,
        }

        quote = quote_map.get(sym)
        if quote:
            bid = f(getattr(quote, "bid_price", 0.0))
            ask = f(getattr(quote, "ask_price", 0.0))
            ts = getattr(quote, "timestamp", None)

            out["bid"] = bid
            out["ask"] = ask

            if bid > 0 and ask > 0 and ask >= bid:
                mid = (bid + ask) / 2
                out["spread_pct"] = round((ask - bid) / mid, 6)
                out["quote_mid"] = round(mid, 4)

            if ts:
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                out["quote_age_sec"] = round((end - ts.astimezone(timezone.utc)).total_seconds(), 2)

        bars = bars_map.get(sym, [])
        if bars:
            closes = [f(getattr(b, "close", 0.0)) for b in bars if f(getattr(b, "close", 0.0)) > 0]
            highs = [f(getattr(b, "high", 0.0)) for b in bars if f(getattr(b, "high", 0.0)) > 0]
            lows = [f(getattr(b, "low", 0.0)) for b in bars if f(getattr(b, "low", 0.0)) > 0]
            vols = [f(getattr(b, "volume", 0.0)) for b in bars]

            if closes:
                price = closes[-1]
                out["price"] = round(price, 4)
                out["last_bar_close"] = round(price, 4)

                def momentum(minutes: int) -> float:
                    if len(closes) <= minutes:
                        return 0.0
                    return pct(closes[-1], closes[-1 - minutes])

                out["momentum_1m"] = round(momentum(1), 4)
                out["momentum_3m"] = round(momentum(3), 4)
                out["momentum_5m"] = round(momentum(5), 4)

            if highs:
                out["high_of_day"] = round(max(highs), 4)
            if lows:
                out["low_of_day"] = round(min(lows), 4)

            total_volume = sum(vols)
            out["volume"] = round(total_volume, 2)

            pv = 0.0
            vv = 0.0
            for b in bars:
                close = f(getattr(b, "close", 0.0))
                vol = f(getattr(b, "volume", 0.0))
                if close > 0 and vol > 0:
                    pv += close * vol
                    vv += vol

            if vv > 0:
                vwap = pv / vv
                out["vwap"] = round(vwap, 4)
                if out.get("price", 0) > 0:
                    out["vwap_distance_pct"] = round(pct(out["price"], vwap), 4)

            recent5 = sum(vols[-5:]) if len(vols) >= 5 else sum(vols)
            avg5 = (sum(vols) / max(len(vols), 1)) * 5
            if avg5 > 0:
                out["relative_volume"] = round(recent5 / avg5, 4)

            if out.get("price", 0) > 0:
                out["dollar_volume"] = round(out["price"] * total_volume, 2)

            # pullback_depth_pct: how far price has pulled back from HOD (≤ 0)
            if closes and highs:
                hod = max(highs)
                if hod > 0:
                    out["pullback_depth_pct"] = round(pct(closes[-1], hod), 4)

            # candle_strength: last bar body-to-range ratio (0=doji, 1=full body)
            last_bar = bars[-1]
            l_open = f(getattr(last_bar, "open", 0.0))
            l_close = f(getattr(last_bar, "close", 0.0))
            l_high = f(getattr(last_bar, "high", 0.0))
            l_low = f(getattr(last_bar, "low", 0.0))
            bar_range = l_high - l_low
            if bar_range > 0 and l_open > 0 and l_close > 0:
                out["candle_strength"] = round(abs(l_close - l_open) / bar_range, 4)

            # volume_reexpansion: recent 5-bar avg vs prior session baseline
            if len(vols) >= 10:
                recent5_avg = sum(vols[-5:]) / 5.0
                prior_avg = sum(vols[:-5]) / max(len(vols) - 5, 1)
                if prior_avg > 0:
                    out["volume_reexpansion"] = round(recent5_avg / prior_avg, 4)

        daily = daily_map.get(sym, [])
        if daily:
            closes = [f(getattr(b, "close", 0.0)) for b in daily if f(getattr(b, "close", 0.0)) > 0]
            if len(closes) >= 2:
                prev_close = closes[-2]
                out["prev_close"] = round(prev_close, 4)
                if out.get("price", 0) > 0:
                    out["day_move_pct"] = round(pct(out["price"], prev_close), 4)

        enriched[sym] = out

    return enriched, warnings, blockers


def build_prior_runner_scores() -> dict[str, float]:
    """Per-ticker historical success rate from outcome journals, scaled 0-10.
    Blends toward 0.5 prior until 5+ observations so sparse tickers stay neutral."""
    counts: dict[str, int] = {}
    hits: dict[str, int] = {}

    for path in (PRE_JOURNAL, REACTIVE_JOURNAL):
        payload = read_json(path, {})
        closed = payload.get("closed_alerts") or []
        for entry in closed:
            if not isinstance(entry, dict):
                continue
            sym = str(entry.get("ticker") or entry.get("symbol") or "").upper().strip()
            if not sym:
                continue
            counts[sym] = counts.get(sym, 0) + 1
            if entry.get("exit_reason") == "TARGET_HIT":
                hits[sym] = hits.get(sym, 0) + 1

    scores: dict[str, float] = {}
    for sym, n in counts.items():
        empirical = hits.get(sym, 0) / n
        weight = min(n / 5.0, 1.0)
        blended = 0.5 * (1 - weight) + empirical * weight
        scores[sym] = round(blended * 10.0, 4)

    return scores


def main() -> None:
    generated_at = now_iso()
    seed_rows = collect_seed_rows()
    seed_symbols = [ticker(r) for r in seed_rows if ticker(r)]

    # Always include index tickers so market regime filter has real index data.
    symbols = list(dict.fromkeys(seed_symbols + INDEX_TICKERS))

    prior_scores = build_prior_runner_scores()

    blockers: list[str] = []
    warnings: list[str] = []

    if not seed_symbols:
        blockers.append("no_seed_symbols_available")

    market, market_warnings, market_blockers = enrich_with_alpaca(symbols)
    warnings.extend(market_warnings)
    blockers.extend(market_blockers)

    rows: list[dict[str, Any]] = []

    for base in seed_rows:
        sym = ticker(base)
        merged = dict(base)
        merged.update(market.get(sym, {}))

        if sym in prior_scores:
            merged["prior_runner_score"] = prior_scores[sym]

        price = f(merged.get("price"), row_price(base))
        high = f(merged.get("high_of_day"))
        low = f(merged.get("low_of_day"))

        if price > 0:
            merged["price"] = round(price, 4)

        if price > 0 and high > 0:
            merged["high_of_day_distance_pct"] = round(pct(price, high), 4)

        if high > 0 and low > 0:
            merged["intraday_range_pct"] = round(pct(high, low), 4)

        merged["source"] = merged.get("alpaca_feed_used") or merged.get("source") or "ALPACA"
        merged["order_submission"] = False
        merged["live_trading"] = False
        merged["paper_order_allowed"] = False
        merged["live_order_allowed"] = False

        rows.append(merged)

    rows.sort(
        key=lambda r: (
            f(r.get("day_move_pct")),
            f(r.get("relative_volume")),
            f(r.get("dollar_volume")),
        ),
        reverse=True,
    )

    rows_with_price = [r for r in rows if f(r.get("price")) > 0]
    rows_with_day_move = [r for r in rows if r.get("day_move_pct") not in [None, "", 0, 0.0]]
    rows_with_rvol = [r for r in rows if r.get("relative_volume") not in [None, "", 1, 1.0]]
    rows_with_spread = [r for r in rows if r.get("spread_pct") not in [None, "", -1, -1.0]]
    rows_with_quote_age = [r for r in rows if r.get("quote_age_sec") not in [None, "", -1, -1.0]]

    if not rows_with_day_move:
        warnings.append("no_rows_with_day_move")
    if not rows_with_spread:
        warnings.append("no_rows_with_spread")
    if not rows_with_quote_age:
        warnings.append("no_rows_with_quote_age")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "v3_enriched_rows_health_v2",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "rows": len(rows),
        "rows_with_price": len(rows_with_price),
        "rows_with_day_move": len(rows_with_day_move),
        "rows_with_non_default_rvol": len(rows_with_rvol),
        "rows_with_spread": len(rows_with_spread),
        "rows_with_quote_age": len(rows_with_quote_age),
        "top_ticker": rows[0].get("ticker") if rows else None,
        "order_submission": False,
        "live_trading": False,
    }

    payload = {
        "schema_version": "v3_enriched_rows_v2",
        "generated_at": generated_at,
        "health": health,
        "rows": rows,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
            "purpose": "Real Alpaca V3 market enrichment only. Does not trade.",
        },
    }

    write_json(OUT_DOCS, payload)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, payload)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
