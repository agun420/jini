from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SIGNAL_HISTORY_PATH = Path("state/prediction_engine/signal_history.json")
OUTCOME_STATE_PATH = Path("state/prediction_engine/outcome_labels.json")
OUTCOME_DOCS_PATH = Path("docs/data/prediction_engine/outcomes.json")
OUTCOME_HEALTH_PATH = Path("docs/data/prediction_engine/outcome_labeler_health.json")

DASHBOARD_CANDIDATES = [
    Path("docs/data/prediction_engine/signal_dashboard_market_guard_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_quality_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_news_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_finra_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard.json"),
]

HORIZONS_MINUTES = [30, 60, 90]
DEFAULT_TIMEOUT_SECONDS = 20


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_utc_iso() -> str:
    return now_utc().isoformat()


def parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def safe_symbol(row: Dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    try:
        raw = path.read_text(encoding="utf-8").strip()
        return json.loads(raw) if raw else default
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")


def extract_signal_rows(payload: Any) -> List[Dict[str, Any]]:
    """
    Accepts common shapes from Package 4 or dashboard JSON:
    - [rows]
    - {"rows": [...]}
    - {"signals": [...]}
    - {"history": [...]}
    - {"events": [...]}
    """
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        for key in ("rows", "signals", "history", "events", "items", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

    return []


def load_signal_history() -> Tuple[List[Dict[str, Any]], str]:
    payload = read_json(SIGNAL_HISTORY_PATH, {})
    rows = extract_signal_rows(payload)
    return rows, str(SIGNAL_HISTORY_PATH)


def latest_dashboard_prices() -> Tuple[Dict[str, float], str]:
    for path in DASHBOARD_CANDIDATES:
        payload = read_json(path, {})
        rows = extract_signal_rows(payload)
        if not rows:
            continue

        prices: Dict[str, float] = {}
        for row in rows:
            ticker = safe_symbol(row)
            price = safe_float(row.get("price"))
            if ticker and price and price > 0:
                prices[ticker] = price

        if prices:
            return prices, str(path)

    return {}, "none"


def normalize_signal(row: Dict[str, Any], idx: int) -> Optional[Dict[str, Any]]:
    ticker = safe_symbol(row)
    if not ticker:
        return None

    # Package 4 may use timestamp/generated_at/signal_time/run_time depending on source.
    ts = (
        row.get("timestamp")
        or row.get("signal_time")
        or row.get("generated_at")
        or row.get("run_time")
        or row.get("created_at")
    )

    signal_dt = parse_ts(ts)
    if signal_dt is None:
        # Keep row but mark as not labelable.
        signal_dt = now_utc()

    price = safe_float(
        row.get("price")
        or row.get("entry")
        or row.get("entry_price")
        or row.get("alert_price")
    )

    target = safe_float(row.get("target") or row.get("target_price"))
    stop = safe_float(row.get("stop") or row.get("stop_price"))

    # If target/stop do not exist, create research-only default levels.
    if price and price > 0:
        if target is None:
            target = round(price * 1.03, 4)
        if stop is None:
            stop = round(price * 0.985, 4)

    unique_id = (
        row.get("signal_id")
        or row.get("id")
        or f"{ticker}:{signal_dt.isoformat()}:{idx}"
    )

    return {
        "signal_id": str(unique_id),
        "ticker": ticker,
        "signal_time": signal_dt.isoformat(),
        "status": row.get("status") or row.get("signal") or "UNKNOWN",
        "score": safe_float(row.get("score"), None),
        "price": price,
        "entry": safe_float(row.get("entry"), price),
        "target": target,
        "stop": stop,
        "source_status": row.get("status"),
        "source_reason": row.get("trade_gate_summary") or row.get("reason"),
        "raw": row,
    }


def alpaca_headers() -> Optional[Dict[str, str]]:
    key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
    secret = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")

    if not key or not secret:
        return None

    return {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
    }


def fetch_alpaca_bars(
    symbols: List[str],
    start: datetime,
    end: datetime,
    headers: Dict[str, str],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Uses Alpaca market data v2 with IEX feed.
    This is optional. If keys are missing or request fails, the labeler falls back safely.
    """
    if not symbols:
        return {}

    url = "https://data.alpaca.markets/v2/stocks/bars"
    query = urlencode(
        {
            "symbols": ",".join(sorted(set(symbols))),
            "timeframe": "1Min",
            "start": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "end": end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "feed": "iex",
            "limit": 10000,
        }
    )

    request = Request(f"{url}?{query}", headers=headers, method="GET")

    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"Alpaca bars fetch failed safely: {exc}", file=sys.stderr)
        return {}

    bars = payload.get("bars")
    if not isinstance(bars, dict):
        return {}

    clean: Dict[str, List[Dict[str, Any]]] = {}
    for symbol, items in bars.items():
        if isinstance(items, list):
            clean[str(symbol).upper()] = [item for item in items if isinstance(item, dict)]

    return clean


def bar_high_low_close(bars: List[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    highs = [safe_float(bar.get("h")) for bar in bars]
    lows = [safe_float(bar.get("l")) for bar in bars]
    closes = [safe_float(bar.get("c")) for bar in bars]

    highs = [x for x in highs if x is not None]
    lows = [x for x in lows if x is not None]
    closes = [x for x in closes if x is not None]

    return (
        max(highs) if highs else None,
        min(lows) if lows else None,
        closes[-1] if closes else None,
    )


def label_from_bars(
    signal: Dict[str, Any],
    bars: List[Dict[str, Any]],
    horizon_minutes: int,
) -> Dict[str, Any]:
    entry = safe_float(signal.get("entry") or signal.get("price"))
    target = safe_float(signal.get("target"))
    stop = safe_float(signal.get("stop"))

    signal_dt = parse_ts(signal.get("signal_time"))
    end_dt = signal_dt + timedelta(minutes=horizon_minutes) if signal_dt else None

    if not entry or entry <= 0:
        return {
            "label": "UNLABELABLE",
            "reason": "missing_entry_price",
        }

    filtered: List[Dict[str, Any]] = []
    for bar in bars:
        bar_dt = parse_ts(bar.get("t"))
        if not bar_dt or not signal_dt or not end_dt:
            continue
        if signal_dt <= bar_dt <= end_dt:
            filtered.append(bar)

    if not filtered:
        return {
            "label": "NO_BAR_DATA",
            "reason": "no_bars_in_horizon",
            "horizon_minutes": horizon_minutes,
        }

    hit_target_at = None
    hit_stop_at = None

    for bar in filtered:
        bar_dt = parse_ts(bar.get("t"))
        high = safe_float(bar.get("h"))
        low = safe_float(bar.get("l"))

        if target and high is not None and high >= target and hit_target_at is None:
            hit_target_at = bar_dt

        if stop and low is not None and low <= stop and hit_stop_at is None:
            hit_stop_at = bar_dt

        if hit_target_at and hit_stop_at:
            break

    high, low, close = bar_high_low_close(filtered)
    max_return_pct = ((high - entry) / entry * 100.0) if high is not None else None
    min_return_pct = ((low - entry) / entry * 100.0) if low is not None else None
    close_return_pct = ((close - entry) / entry * 100.0) if close is not None else None

    if hit_target_at and (not hit_stop_at or hit_target_at <= hit_stop_at):
        label = "TARGET_BEFORE_STOP"
    elif hit_stop_at and (not hit_target_at or hit_stop_at < hit_target_at):
        label = "STOP_BEFORE_TARGET"
    else:
        label = "TIME_EXPIRED"

    return {
        "label": label,
        "reason": "bar_path_available",
        "horizon_minutes": horizon_minutes,
        "bars_used": len(filtered),
        "target": target,
        "stop": stop,
        "high_in_window": high,
        "low_in_window": low,
        "close_in_window": close,
        "max_return_pct": round(max_return_pct, 4) if max_return_pct is not None else None,
        "min_return_pct": round(min_return_pct, 4) if min_return_pct is not None else None,
        "close_return_pct": round(close_return_pct, 4) if close_return_pct is not None else None,
        "hit_target_at": hit_target_at.isoformat() if hit_target_at else None,
        "hit_stop_at": hit_stop_at.isoformat() if hit_stop_at else None,
    }


def label_from_latest_price(
    signal: Dict[str, Any],
    latest_prices: Dict[str, float],
    horizon_minutes: int,
) -> Dict[str, Any]:
    ticker = signal["ticker"]
    entry = safe_float(signal.get("entry") or signal.get("price"))
    latest = latest_prices.get(ticker)

    if not entry or entry <= 0:
        return {
            "label": "UNLABELABLE",
            "reason": "missing_entry_price",
        }

    if not latest or latest <= 0:
        return {
            "label": "NO_PRICE_DATA",
            "reason": "missing_latest_price",
            "horizon_minutes": horizon_minutes,
        }

    ret = (latest - entry) / entry * 100.0

    return {
        "label": "PRICE_ONLY",
        "reason": "latest_price_only_no_bar_path",
        "horizon_minutes": horizon_minutes,
        "latest_price": latest,
        "close_return_pct": round(ret, 4),
    }


def summarize(labels: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_label: Dict[str, int] = {}
    by_status: Dict[str, Dict[str, int]] = {}
    returns: List[float] = []

    for item in labels:
        for outcome in item.get("outcomes", []):
            label = outcome.get("label", "UNKNOWN")
            by_label[label] = by_label.get(label, 0) + 1

            if isinstance(outcome.get("close_return_pct"), (int, float)):
                returns.append(float(outcome["close_return_pct"]))

        status = str(item.get("status") or "UNKNOWN")
        by_status.setdefault(status, {"signals": 0})
        by_status[status]["signals"] += 1

    avg_return = sum(returns) / len(returns) if returns else None

    return {
        "total_signals_labeled": len(labels),
        "outcomes_by_label": by_label,
        "signals_by_status": by_status,
        "average_close_return_pct": round(avg_return, 4) if avg_return is not None else None,
        "return_observation_count": len(returns),
    }


def build_outcomes() -> Dict[str, Any]:
    history_rows, history_source = load_signal_history()
    latest_prices, latest_price_source = latest_dashboard_prices()

    normalized = [
        row for row in (
            normalize_signal(item, idx)
            for idx, item in enumerate(history_rows)
        )
        if row is not None
    ]

    # Only label recent-ish rows to keep GitHub Action runs light.
    cutoff = now_utc() - timedelta(days=int(os.getenv("OUTCOME_LOOKBACK_DAYS", "7")))
    normalized = [
        row for row in normalized
        if (parse_ts(row.get("signal_time")) or now_utc()) >= cutoff
    ]

    headers = alpaca_headers()
    bars_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    alpaca_used = False

    if headers and normalized:
        start_times = [parse_ts(row["signal_time"]) for row in normalized]
        start_times = [dt for dt in start_times if dt is not None]
        if start_times:
            start = min(start_times)
            end = now_utc()
            symbols = sorted({row["ticker"] for row in normalized})
            bars_by_symbol = fetch_alpaca_bars(symbols, start, end, headers)
            alpaca_used = bool(bars_by_symbol)

    labeled: List[Dict[str, Any]] = []

    for signal in normalized:
        signal_dt = parse_ts(signal.get("signal_time")) or now_utc()
        age_minutes = (now_utc() - signal_dt).total_seconds() / 60.0

        outcomes: List[Dict[str, Any]] = []

        for horizon in HORIZONS_MINUTES:
            if age_minutes < horizon:
                outcomes.append(
                    {
                        "label": "PENDING",
                        "reason": "horizon_not_reached",
                        "horizon_minutes": horizon,
                        "age_minutes": round(age_minutes, 2),
                    }
                )
                continue

            bars = bars_by_symbol.get(signal["ticker"], [])
            if bars:
                outcome = label_from_bars(signal, bars, horizon)
            else:
                outcome = label_from_latest_price(signal, latest_prices, horizon)

            outcomes.append(outcome)

        labeled.append(
            {
                "signal_id": signal["signal_id"],
                "ticker": signal["ticker"],
                "signal_time": signal["signal_time"],
                "status": signal["status"],
                "score": signal.get("score"),
                "entry": signal.get("entry") or signal.get("price"),
                "target": signal.get("target"),
                "stop": signal.get("stop"),
                "source_reason": signal.get("source_reason"),
                "outcomes": outcomes,
            }
        )

    payload = {
        "schema_version": "outcome_labeler_v1",
        "generated_at": now_utc_iso(),
        "status": "PASS",
        "mode": "paper_only_research",
        "history_source": history_source,
        "latest_price_source": latest_price_source,
        "alpaca_bars_used": alpaca_used,
        "horizons_minutes": HORIZONS_MINUTES,
        "summary": summarize(labeled),
        "rows": labeled,
        "safety": {
            "paper_only": True,
            "order_submission": False,
            "live_trading": False,
            "changes_thresholds": False,
            "disclaimer": "Outcome labels are for research only. Not financial advice.",
        },
    }

    return payload


def export_outcomes() -> Dict[str, Any]:
    payload = build_outcomes()

    health = {
        "schema_version": "outcome_labeler_health_v1",
        "generated_at": payload["generated_at"],
        "status": payload["status"],
        "rows_labeled": payload["summary"]["total_signals_labeled"],
        "alpaca_bars_used": payload["alpaca_bars_used"],
        "history_source": payload["history_source"],
        "latest_price_source": payload["latest_price_source"],
        "order_submission": False,
        "paper_only": True,
        "notes": [
            "Package 5 labels outcomes from the signal journal.",
            "If Alpaca keys are present, it can use IEX 1-minute bars for target-before-stop labels.",
            "If Alpaca bars are unavailable, it falls back to latest-price-only labels.",
            "Package 5 does not place orders and does not change thresholds.",
        ],
    }

    write_json(OUTCOME_STATE_PATH, payload)
    write_json(OUTCOME_DOCS_PATH, payload)
    write_json(OUTCOME_HEALTH_PATH, health)

    return {
        "status": "PASS",
        "rows_labeled": payload["summary"]["total_signals_labeled"],
        "alpaca_bars_used": payload["alpaca_bars_used"],
        "output_state": str(OUTCOME_STATE_PATH),
        "output_docs": str(OUTCOME_DOCS_PATH),
        "health_path": str(OUTCOME_HEALTH_PATH),
    }


def main() -> None:
    print(json.dumps(export_outcomes(), indent=2))


if __name__ == "__main__":
    main()
