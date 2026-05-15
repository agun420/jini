from __future__ import annotations

import json
import os
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo


CANDIDATE_OUTPUT_PATH = Path("state/prediction_engine/dynamic_alpaca_candidates.json")
HEALTH_OUTPUT_PATH = Path("docs/data/prediction_engine/alpaca_market_scanner_health.json")

NY_TZ = ZoneInfo("America/New_York")

DEFAULT_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META", "AMZN", "GOOGL", "PLTR", "SMCI",
    "SOFI", "RIVN", "MARA", "RIOT", "COIN", "HOOD", "NIO", "LCID", "SOUN", "IONQ",
    "QBTS", "ACHR", "JOBY", "RKLB", "OPEN", "UPST", "AFRM", "BBAI", "AI", "SERV",
    "MSTR", "AVGO", "NFLX", "CRM", "UBER", "SHOP", "SNOW", "NET", "DDOG", "CRWD",
    "GME", "AMC", "TLRY", "HIMS", "DNA", "PATH", "U", "DKNG", "ROKU", "PYPL",
]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_utc_iso() -> str:
    return _now_utc().isoformat()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=False), encoding="utf-8")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_universe() -> List[str]:
    raw = os.getenv("SCANNER_UNIVERSE", "").strip()
    if raw:
        symbols = [item.strip().upper() for item in raw.split(",") if item.strip()]
    else:
        symbols = DEFAULT_UNIVERSE[:]

    max_symbols = int(os.getenv("SCANNER_MAX_SYMBOLS", "75"))
    seen = set()
    cleaned: List[str] = []

    for symbol in symbols:
        if not symbol or symbol in seen:
            continue
        # Keep the scanner conservative. No OTC style symbols in this v1.
        if not symbol.replace(".", "").replace("-", "").isalnum():
            continue
        seen.add(symbol)
        cleaned.append(symbol)

    return cleaned[:max_symbols]


def _chunked(items: List[str], size: int) -> Iterable[List[str]]:
    for idx in range(0, len(items), size):
        yield items[idx : idx + size]


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        if isinstance(value, float) and math.isnan(value):
            return default
        return float(value)
    except Exception:
        return default


def _pct(current: Optional[float], base: Optional[float]) -> Optional[float]:
    if current is None or base in (None, 0):
        return None
    return (current - base) / base * 100.0


def _round(value: Optional[float], digits: int = 4) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), digits)


def _bar_to_dict(bar: Any) -> Dict[str, Any]:
    """
    Alpaca-py bars expose attributes. This helper keeps the rest of the scanner
    decoupled from the SDK object shape.
    """
    ts = getattr(bar, "timestamp", None)
    if ts is None:
        ts = getattr(bar, "t", None)

    if ts is not None and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    return {
        "timestamp": ts,
        "open": _safe_float(getattr(bar, "open", getattr(bar, "o", None))),
        "high": _safe_float(getattr(bar, "high", getattr(bar, "h", None))),
        "low": _safe_float(getattr(bar, "low", getattr(bar, "l", None))),
        "close": _safe_float(getattr(bar, "close", getattr(bar, "c", None))),
        "volume": _safe_float(getattr(bar, "volume", getattr(bar, "v", None)), 0.0) or 0.0,
    }


def _session_date(ts: datetime) -> str:
    return ts.astimezone(NY_TZ).date().isoformat()


def _is_regular_market_bar(ts: datetime) -> bool:
    local = ts.astimezone(NY_TZ)
    hhmm = local.hour * 100 + local.minute
    return 930 <= hhmm <= 1600


def _calc_vwap(bars: List[Dict[str, Any]]) -> Optional[float]:
    total_dollars = 0.0
    total_volume = 0.0

    for bar in bars:
        high = bar.get("high")
        low = bar.get("low")
        close = bar.get("close")
        volume = bar.get("volume") or 0.0

        if high is None or low is None or close is None or volume <= 0:
            continue

        typical = (high + low + close) / 3.0
        total_dollars += typical * volume
        total_volume += volume

    if total_volume <= 0:
        return None

    return total_dollars / total_volume


def _calc_volume_acceleration(session_bars: List[Dict[str, Any]]) -> Optional[float]:
    if len(session_bars) < 10:
        return None

    last_5 = sum((bar.get("volume") or 0.0) for bar in session_bars[-5:])
    prior_5 = sum((bar.get("volume") or 0.0) for bar in session_bars[-10:-5])

    if prior_5 <= 0:
        return None

    return last_5 / prior_5


def _calc_relative_volume(
    grouped_by_date: Dict[str, List[Dict[str, Any]]],
    current_date: str,
    current_count: int,
    current_volume: float,
) -> Optional[float]:
    if current_count <= 0 or current_volume <= 0:
        return None

    prior_cumulative: List[float] = []

    for date_key in sorted(grouped_by_date.keys()):
        if date_key >= current_date:
            continue

        bars = grouped_by_date[date_key]
        if not bars:
            continue

        comparison = bars[:current_count]
        if not comparison:
            continue

        volume = sum((bar.get("volume") or 0.0) for bar in comparison)
        if volume > 0:
            prior_cumulative.append(volume)

    if not prior_cumulative:
        return None

    avg_prior = sum(prior_cumulative) / len(prior_cumulative)
    if avg_prior <= 0:
        return None

    return current_volume / avg_prior


def _derive_features(symbol: str, raw_bars: List[Any]) -> Optional[Dict[str, Any]]:
    bars = [_bar_to_dict(bar) for bar in raw_bars]
    bars = [
        bar
        for bar in bars
        if isinstance(bar.get("timestamp"), datetime)
        and bar.get("close") is not None
        and _is_regular_market_bar(bar["timestamp"])
    ]

    bars.sort(key=lambda item: item["timestamp"])

    if not bars:
        return None

    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for bar in bars:
        grouped[_session_date(bar["timestamp"])].append(bar)

    session_dates = sorted(grouped.keys())
    current_date = session_dates[-1]
    current_session = grouped[current_date]

    if not current_session:
        return None

    previous_close = None
    for date_key in reversed(session_dates[:-1]):
        prior_bars = grouped[date_key]
        if prior_bars:
            previous_close = prior_bars[-1].get("close")
            break

    first_bar = current_session[0]
    last_bar = current_session[-1]

    open_price = first_bar.get("open")
    current_price = last_bar.get("close")
    current_volume = sum((bar.get("volume") or 0.0) for bar in current_session)
    vwap = _calc_vwap(current_session)

    gap_pct = _pct(open_price, previous_close)
    day_change_pct = _pct(current_price, open_price)
    vwap_distance_pct = _pct(current_price, vwap)
    relative_volume = _calc_relative_volume(grouped, current_date, len(current_session), current_volume)
    volume_acceleration = _calc_volume_acceleration(current_session)

    # Simple transparent score hint for dedupe. Package 1A performs final scoring.
    score_hint = 0.0
    if day_change_pct is not None and day_change_pct > 0:
        score_hint += min(day_change_pct, 25)
    if relative_volume is not None:
        score_hint += min(relative_volume * 10, 35)
    if vwap_distance_pct is not None and 0 <= vwap_distance_pct <= 6:
        score_hint += 20
    if volume_acceleration is not None and volume_acceleration >= 1.2:
        score_hint += 10

    data_age_seconds = (_now_utc() - last_bar["timestamp"].astimezone(timezone.utc)).total_seconds()

    # Alpaca free/IEX can be delayed depending on endpoint/account. Treat too-old data as stale.
    candidate_quality = "GOOD"
    if data_age_seconds > 45 * 60:
        candidate_quality = "STALE"

    return {
        "ticker": symbol,
        "symbol": symbol,
        "source_type": "alpaca_iex_market_scanner",
        "primary_source": "alpaca_iex",
        "candidate_quality": candidate_quality,
        "bar_timeframe_used": "1Min",
        "session_date": current_date,
        "last_bar_time": last_bar["timestamp"].astimezone(timezone.utc).isoformat(),
        "data_age_seconds": round(data_age_seconds, 2),
        "price": _round(current_price, 4),
        "open": _round(open_price, 4),
        "previous_close": _round(previous_close, 4),
        "volume": int(current_volume),
        "vwap": _round(vwap, 4),
        "gap_pct": _round(gap_pct, 2),
        "day_change_pct": _round(day_change_pct, 2),
        "relative_volume": _round(relative_volume, 2),
        "vwap_distance_pct": _round(vwap_distance_pct, 2),
        "volume_acceleration": _round(volume_acceleration, 2),
        "score": round(score_hint, 2),
        "features": {
            "gap_pct": _round(gap_pct, 2),
            "day_change_pct": _round(day_change_pct, 2),
            "relative_volume": _round(relative_volume, 2),
            "vwap": _round(vwap, 4),
            "vwap_distance_pct": _round(vwap_distance_pct, 2),
            "volume_acceleration": _round(volume_acceleration, 2),
            "session_bar_count": len(current_session),
            "current_session_volume": int(current_volume),
        },
    }


def _load_alpaca_sdk() -> Tuple[Any, Any, Any, Any]:
    try:
        from alpaca.data.enums import DataFeed
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
    except Exception as exc:
        raise RuntimeError(
            "alpaca-py is not installed. Install it with: pip install alpaca-py"
        ) from exc

    return StockHistoricalDataClient, StockBarsRequest, TimeFrame, DataFeed


def fetch_alpaca_candidates() -> Dict[str, Any]:
    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    secret_key = os.getenv("ALPACA_SECRET_KEY", "").strip()

    if not api_key or not secret_key:
        return {
            "status": "NO_KEYS",
            "rows": [],
            "error": "Missing ALPACA_API_KEY or ALPACA_SECRET_KEY. No live candidates generated.",
        }

    StockHistoricalDataClient, StockBarsRequest, TimeFrame, DataFeed = _load_alpaca_sdk()

    symbols = _parse_universe()
    lookback_days = int(os.getenv("ALPACA_DATA_LOOKBACK_DAYS", "7"))
    chunk_size = int(os.getenv("ALPACA_CHUNK_SIZE", "50"))

    # Use a small delay buffer. This avoids common free-data timing problems.
    end = _now_utc() - timedelta(minutes=int(os.getenv("ALPACA_END_DELAY_MINUTES", "16")))
    start = end - timedelta(days=lookback_days)

    client = StockHistoricalDataClient(api_key, secret_key)

    rows: List[Dict[str, Any]] = []
    errors: List[str] = []

    for chunk in _chunked(symbols, chunk_size):
        try:
            request = StockBarsRequest(
                symbol_or_symbols=chunk,
                timeframe=TimeFrame.Minute,
                start=start,
                end=end,
                feed=DataFeed.IEX,
            )
            response = client.get_stock_bars(request)

            # alpaca-py normally exposes .data as Dict[str, List[Bar]]
            data = getattr(response, "data", None)
            if not isinstance(data, dict):
                data = {}

            for symbol in chunk:
                raw_bars = data.get(symbol, [])
                candidate = _derive_features(symbol, raw_bars)
                if candidate:
                    rows.append(candidate)

        except Exception as exc:
            errors.append(f"{','.join(chunk)}: {type(exc).__name__}: {exc}")

    rows.sort(
        key=lambda item: (
            float(item.get("score") or 0),
            float(item.get("relative_volume") or 0),
            float(item.get("day_change_pct") or 0),
        ),
        reverse=True,
    )

    return {
        "status": "PASS" if rows else "EMPTY",
        "rows": rows[:75],
        "errors": errors[:10],
        "universe_count": len(symbols),
        "lookback_days": lookback_days,
        "end_delay_minutes": int(os.getenv("ALPACA_END_DELAY_MINUTES", "16")),
    }


def export_alpaca_candidates() -> Dict[str, Any]:
    generated_at = _now_utc_iso()

    try:
        result = fetch_alpaca_candidates()
    except Exception as exc:
        result = {
            "status": "ERROR",
            "rows": [],
            "error": f"{type(exc).__name__}: {exc}",
            "errors": [f"{type(exc).__name__}: {exc}"],
        }

    rows = result.get("rows", []) if isinstance(result.get("rows"), list) else []

    payload = {
        "schema_version": "alpaca_free_market_candidates_v1",
        "generated_at": generated_at,
        "status": result.get("status", "UNKNOWN"),
        "mode": "paper_only_research",
        "feed": "IEX",
        "rows": rows,
        "safety": {
            "paper_only": True,
            "order_submission": False,
            "live_trading": False,
            "free_api_only": True,
            "disclaimer": "Market-data scanner only. Not financial advice. No orders submitted.",
        },
    }

    health = {
        "schema_version": "alpaca_market_scanner_health_v1",
        "generated_at": generated_at,
        "status": result.get("status", "UNKNOWN"),
        "row_count": len(rows),
        "universe_count": result.get("universe_count"),
        "lookback_days": result.get("lookback_days"),
        "end_delay_minutes": result.get("end_delay_minutes"),
        "error": result.get("error"),
        "errors": result.get("errors", []),
        "output_path": str(CANDIDATE_OUTPUT_PATH),
        "paper_only": True,
        "order_submission": False,
        "notes": [
            "Package 1B pulls Alpaca free/IEX bar data when keys are present.",
            "This package writes candidate rows only.",
            "Package 1A normalizes and classifies these rows.",
            "No paper or live orders are submitted.",
        ],
    }

    _write_json(CANDIDATE_OUTPUT_PATH, payload)
    _write_json(HEALTH_OUTPUT_PATH, health)

    return {
        "status": result.get("status", "UNKNOWN"),
        "row_count": len(rows),
        "candidate_output_path": str(CANDIDATE_OUTPUT_PATH),
        "health_output_path": str(HEALTH_OUTPUT_PATH),
        "errors": result.get("errors", []),
    }


def main() -> None:
    print(json.dumps(export_alpaca_candidates(), indent=2))


if __name__ == "__main__":
    main()
