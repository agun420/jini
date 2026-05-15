from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from prediction_engine.scanners.free_signal_schema import (
    DataQuality,
    FreeSignal,
    STATUS_ALERT_ONLY,
    STATUS_NO_TRADE,
    STATUS_TRADE_ELIGIBLE,
    STATUS_WAIT_FOR_PULLBACK,
    STATUS_WATCH_ONLY,
    clamp,
    now_utc_iso,
    pct,
    safe_float,
    safe_symbol,
)


CANDIDATE_PATHS = [
    Path("state/prediction_engine/dynamic_alpaca_candidates.json"),
    Path("state/prediction_engine/dynamic_discovery_candidates.json"),
    Path("state/prediction_engine/candidates.json"),
    Path("docs/data/prediction_engine/predictions.json"),
    Path("docs/data/prediction_engine/track_only_candidates.json"),
]

OUTPUT_PATH = Path("docs/data/prediction_engine/free_scanner.json")
HEALTH_PATH = Path("docs/data/prediction_engine/scanner_health.json")


DEFAULT_UNIVERSE = [
    "AAPL",
    "MSFT",
    "NVDA",
    "TSLA",
    "AMD",
    "META",
    "AMZN",
    "GOOGL",
    "PLTR",
    "SMCI",
    "SOFI",
    "RIVN",
    "MARA",
    "RIOT",
    "COIN",
    "HOOD",
    "NIO",
    "LCID",
    "SOUN",
    "IONQ",
    "QBTS",
    "ACHR",
    "JOBY",
    "RKLB",
    "OPEN",
    "UPST",
    "AFRM",
]


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    try:
        raw = path.read_text(encoding="utf-8").strip()
        return json.loads(raw) if raw else default
    except Exception:
        return default


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=False), encoding="utf-8")


def _as_rows(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        for key in ("rows", "candidates", "predictions", "signals", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

    return []


def _features(row: Dict[str, Any]) -> Dict[str, Any]:
    value = row.get("features")
    return value if isinstance(value, dict) else {}


def _field(row: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    features = _features(row)

    for key in keys:
        if key in row and row.get(key) is not None:
            return row.get(key)
        if key in features and features.get(key) is not None:
            return features.get(key)

    return default


def _load_candidate_rows() -> Tuple[List[Dict[str, Any]], List[str]]:
    all_rows: List[Dict[str, Any]] = []
    sources_used: List[str] = []

    for path in CANDIDATE_PATHS:
        payload = _read_json(path, None)
        rows = _as_rows(payload)

        if rows:
            all_rows.extend(rows)
            sources_used.append(str(path))

    deduped: Dict[str, Dict[str, Any]] = {}

    for row in all_rows:
        ticker = safe_symbol(row)
        if not ticker:
            continue

        current_score = safe_float(
            _field(row, "score", "confidence", "interest_score", "rank_score"),
            0.0,
        ) or 0.0

        existing = deduped.get(ticker)
        existing_score = 0.0

        if existing:
            existing_score = safe_float(
                _field(existing, "score", "confidence", "interest_score", "rank_score"),
                0.0,
            ) or 0.0

        if existing is None or current_score >= existing_score:
            deduped[ticker] = row

    return list(deduped.values()), sources_used


def _placeholder_rows() -> List[Dict[str, Any]]:
    return [
        {
            "ticker": ticker,
            "symbol": ticker,
            "price": None,
            "source_type": "placeholder_universe",
            "candidate_quality": "placeholder",
            "status": STATUS_NO_TRADE,
            "track_reason": "No live candidate data found. Placeholder only.",
        }
        for ticker in DEFAULT_UNIVERSE
    ]


def _calc_vwap_distance(price: Optional[float], vwap: Optional[float]) -> Optional[float]:
    if price is None or vwap in (None, 0):
        return None

    return (price - vwap) / vwap * 100.0


def _calc_risk_reward(
    price: Optional[float],
    stop: Optional[float],
    target: Optional[float],
) -> Optional[float]:
    if price is None or stop is None or target is None:
        return None

    downside = price - stop
    upside = target - price

    if downside <= 0 or upside <= 0:
        return None

    return upside / downside


def _derive_trade_levels(
    price: Optional[float],
    vwap: Optional[float],
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    if price is None or price <= 0:
        return None, None, None, None

    entry = round(price, 4)

    if vwap and vwap > 0 and vwap < price:
        stop = round(max(vwap * 0.992, price * 0.985), 4)
    else:
        stop = round(price * 0.985, 4)

    target = round(price * 1.03, 4)

    risk_reward = _calc_risk_reward(entry, stop, target)
    risk_reward = round(risk_reward, 2) if risk_reward is not None else None

    return entry, stop, target, risk_reward


def _data_quality(row: Dict[str, Any], price: Optional[float]) -> DataQuality:
    source_type = str(_field(row, "source_type", "source", default="existing_candidate"))
    quality_raw = str(_field(row, "candidate_quality", "data_quality", default="unknown")).lower()
    timeframe = str(_field(row, "bar_timeframe_used", "timeframe", default="unknown"))

    quality = "GOOD"
    notes: List[str] = []

    if source_type == "placeholder_universe":
        quality = "BAD"
        notes.append("placeholder_only")

    if price is None:
        quality = "BAD"
        notes.append("missing_price")

    if "daily" in quality_raw or timeframe == "1Day":
        quality = "STALE"
        notes.append("daily_or_fallback_data")

    fallback_used = bool(_field(row, "fallback_used", default=False)) or "fallback" in quality_raw

    return DataQuality(
        primary_source=str(_field(row, "primary_source", "source", default=source_type)),
        fallback_used=fallback_used,
        data_age_seconds=safe_float(_field(row, "data_age_seconds"), None),
        quality=quality,
        notes=notes,
    )


def _score_components(
    price: Optional[float],
    gap_pct: Optional[float],
    day_change_pct: Optional[float],
    relative_volume: Optional[float],
    vwap_distance_pct: Optional[float],
    volume_acceleration: Optional[float],
    risk_reward: Optional[float],
    data_quality: DataQuality,
) -> Tuple[float, Dict[str, float], List[str]]:
    reasons: List[str] = []
    components: Dict[str, float] = {}

    momentum = 0.0

    if day_change_pct is not None:
        if 3 <= day_change_pct <= 25:
            momentum += 20
            reasons.append("controlled day momentum")
        elif 25 < day_change_pct <= 60:
            momentum += 12
            reasons.append("strong but extended day move")
        elif day_change_pct > 60:
            momentum += 5
            reasons.append("very extended day move")
        elif day_change_pct > 0:
            momentum += 8
            reasons.append("positive day move")

    if gap_pct is not None:
        if 2 <= gap_pct <= 15:
            momentum += 8
            reasons.append("healthy gap")
        elif gap_pct > 30:
            momentum -= 6
            reasons.append("gap extension risk")

    components["momentum"] = clamp(momentum, 0, 28)

    volume = 0.0

    if relative_volume is not None:
        if relative_volume >= 5:
            volume += 24
            reasons.append("very strong relative volume")
        elif relative_volume >= 2:
            volume += 20
            reasons.append("strong relative volume")
        elif relative_volume >= 1.5:
            volume += 12
            reasons.append("moderate relative volume")
        elif relative_volume > 0:
            volume += 5
            reasons.append("weak relative volume")

    if volume_acceleration is not None:
        if volume_acceleration >= 1.5:
            volume += 6
            reasons.append("volume acceleration")
        elif volume_acceleration < 0.75:
            volume -= 4
            reasons.append("volume fading")

    components["volume"] = clamp(volume, 0, 26)

    trend = 0.0

    if vwap_distance_pct is not None:
        if 0 <= vwap_distance_pct <= 4:
            trend += 22
            reasons.append("above VWAP and controlled")
        elif 4 < vwap_distance_pct <= 6:
            trend += 15
            reasons.append("above VWAP but extended")
        elif 6 < vwap_distance_pct <= 10:
            trend += 8
            reasons.append("too extended above VWAP")
        elif vwap_distance_pct < 0:
            trend += 2
            reasons.append("below VWAP")

    components["trend"] = clamp(trend, 0, 22)

    risk_quality = 12.0

    if price is None or price <= 0:
        risk_quality -= 12
    elif price < 3:
        risk_quality -= 10
        reasons.append("below minimum price")
    else:
        risk_quality += 2

    if risk_reward is not None:
        if risk_reward >= 2:
            risk_quality += 8
            reasons.append("risk/reward acceptable")
        elif risk_reward < 1.5:
            risk_quality -= 5
            reasons.append("risk/reward weak")

    if data_quality.quality in {"STALE", "BAD"}:
        risk_quality -= 12
        reasons.append("data quality risk")
    elif data_quality.quality == "GOOD":
        risk_quality += 4

    components["risk_quality"] = clamp(risk_quality, 0, 24)

    total_score = round(clamp(sum(components.values())), 2)

    return total_score, components, reasons


def _classify_signal(
    score: float,
    price: Optional[float],
    relative_volume: Optional[float],
    vwap_distance_pct: Optional[float],
    risk_reward: Optional[float],
    data_quality: DataQuality,
) -> Tuple[str, List[str]]:
    blocks: List[str] = []

    if price is None or price <= 0:
        blocks.append("missing_price")
    elif price < 3:
        blocks.append("price_below_3")

    if data_quality.quality in {"STALE", "BAD"}:
        blocks.append("data_not_tradeable")

    if vwap_distance_pct is None:
        blocks.append("missing_vwap")
    elif vwap_distance_pct < 0:
        blocks.append("below_vwap")
    elif vwap_distance_pct > 6:
        blocks.append("too_extended_above_vwap")

    if relative_volume is None:
        blocks.append("missing_relative_volume")
    elif relative_volume < 1.5:
        blocks.append("relative_volume_too_low")

    if risk_reward is None or risk_reward < 2:
        blocks.append("risk_reward_below_2")

    if blocks:
        if "too_extended_above_vwap" in blocks and score >= 70:
            return STATUS_WAIT_FOR_PULLBACK, blocks

        if score >= 65:
            return STATUS_ALERT_ONLY, blocks

        if score >= 40:
            return STATUS_WATCH_ONLY, blocks

        return STATUS_NO_TRADE, blocks

    if score >= 85 and relative_volume is not None and relative_volume >= 2:
        return STATUS_TRADE_ELIGIBLE, []

    if score >= 70:
        return STATUS_ALERT_ONLY, ["needs_stronger_confirmation"]

    if score >= 45:
        return STATUS_WATCH_ONLY, ["score_not_high_enough"]

    return STATUS_NO_TRADE, ["weak_setup"]


def normalize_candidate(row: Dict[str, Any]) -> FreeSignal:
    ticker = safe_symbol(row)

    price = safe_float(_field(row, "price", "alert_price", "close", "c"), None)
    open_price = safe_float(_field(row, "open", "session_open", "o"), None)
    previous_close = safe_float(_field(row, "previous_close", "prev_close", "prior_close"), None)

    raw_gap_pct = safe_float(_field(row, "gap_pct", "gap_percent"), None)
    raw_day_change_pct = safe_float(
        _field(row, "day_change_pct", "day_move_percent", "day_change_percent"),
        None,
    )

    relative_volume = safe_float(_field(row, "relative_volume", "rvol"), None)

    vwap = safe_float(_field(row, "vwap"), None)
    raw_vwap_distance_pct = safe_float(
        _field(row, "vwap_distance_pct", "vwap_distance_percent"),
        None,
    )

    volume_acceleration = safe_float(
        _field(row, "volume_acceleration", "volume_accel"),
        None,
    )

    gap_pct = raw_gap_pct if raw_gap_pct is not None else pct(price, previous_close)
    day_change_pct = raw_day_change_pct if raw_day_change_pct is not None else pct(price, open_price)
    vwap_distance_pct = (
        raw_vwap_distance_pct
        if raw_vwap_distance_pct is not None
        else _calc_vwap_distance(price, vwap)
    )

    data_quality = _data_quality(row, price)

    entry, stop, target, risk_reward = _derive_trade_levels(price, vwap)

    score, components, score_reasons = _score_components(
        price=price,
        gap_pct=gap_pct,
        day_change_pct=day_change_pct,
        relative_volume=relative_volume,
        vwap_distance_pct=vwap_distance_pct,
        volume_acceleration=volume_acceleration,
        risk_reward=risk_reward,
        data_quality=data_quality,
    )

    status, no_trade_reasons = _classify_signal(
        score=score,
        price=price,
        relative_volume=relative_volume,
        vwap_distance_pct=vwap_distance_pct,
        risk_reward=risk_reward,
        data_quality=data_quality,
    )

    if vwap_distance_pct is None:
        trend_state = "UNKNOWN"
    elif vwap_distance_pct < 0:
        trend_state = "BELOW_VWAP"
    elif vwap_distance_pct <= 4:
        trend_state = "BULLISH_CONTROLLED"
    elif vwap_distance_pct <= 6:
        trend_state = "BULLISH_EXTENDED"
    else:
        trend_state = "CHASE_RISK"

    reason = ", ".join(score_reasons[:6]) if score_reasons else "No strong setup detected."

    return FreeSignal(
        ticker=ticker,
        status=status,
        score=score,
        price=round(price, 4) if price is not None else 0.0,
        gap_pct=round(gap_pct, 2) if gap_pct is not None else None,
        day_change_pct=round(day_change_pct, 2) if day_change_pct is not None else None,
        relative_volume=round(relative_volume, 2) if relative_volume is not None else None,
        vwap=round(vwap, 4) if vwap is not None else None,
        vwap_distance_pct=round(vwap_distance_pct, 2) if vwap_distance_pct is not None else None,
        volume_acceleration=round(volume_acceleration, 2) if volume_acceleration is not None else None,
        trend_state=trend_state,
        entry=entry,
        stop=stop,
        target=target,
        risk_reward=risk_reward,
        reason=reason,
        no_trade_reasons=no_trade_reasons,
        data_quality=data_quality,
        source_type=str(_field(row, "source_type", default="existing_candidate")),
    )


def build_payload() -> Dict[str, Any]:
    candidate_rows, sources_used = _load_candidate_rows()

    used_placeholders = False

    if not candidate_rows:
        candidate_rows = _placeholder_rows()
        sources_used = ["placeholder_universe"]
        used_placeholders = True

    signals = [
        normalize_candidate(row).to_dict()
        for row in candidate_rows
        if safe_symbol(row)
    ]

    signals.sort(
        key=lambda row: (
            1 if row.get("status") == STATUS_TRADE_ELIGIBLE else 0,
            float(row.get("score") or 0),
            float(row.get("day_change_pct") or 0),
        ),
        reverse=True,
    )

    signals = signals[:50]

    real_rows = [
        row for row in signals
        if row.get("source_type") != "placeholder_universe"
        and (row.get("data_quality") or {}).get("quality") != "BAD"
    ]

    placeholder_rows = len(signals) - len(real_rows)

    counts = {
        "total": len(signals),
        "real_rows": len(real_rows),
        "placeholder_rows": placeholder_rows,
        "trade_eligible": sum(1 for row in signals if row.get("status") == STATUS_TRADE_ELIGIBLE),
        "wait_for_pullback": sum(1 for row in signals if row.get("status") == STATUS_WAIT_FOR_PULLBACK),
        "alert_only": sum(1 for row in signals if row.get("status") == STATUS_ALERT_ONLY),
        "watch_only": sum(1 for row in signals if row.get("status") == STATUS_WATCH_ONLY),
        "no_trade": sum(1 for row in signals if row.get("status") == STATUS_NO_TRADE),
    }

    best_trade_eligible = next(
        (row for row in signals if row.get("status") == STATUS_TRADE_ELIGIBLE),
        None,
    )

    payload = {
        "schema_version": "free_scanner_normalizer_v1",
        "generated_at": now_utc_iso(),
        "status": "PASS",
        "mode": "paper_only_research",
        "sources_used": sources_used,
        "used_placeholders": used_placeholders,
        "counts": counts,
        "best_trade_eligible": best_trade_eligible,
        "rows": signals,
        "safety": {
            "paper_only": True,
            "order_submission": False,
            "live_trading": False,
            "free_api_only": True,
            "max_notional_per_trade": 2000,
            "allowed_to_trade_status": STATUS_TRADE_ELIGIBLE,
            "blocked_statuses": [
                STATUS_WAIT_FOR_PULLBACK,
                STATUS_ALERT_ONLY,
                STATUS_WATCH_ONLY,
                STATUS_NO_TRADE,
            ],
            "disclaimer": "Research scanner only. Not financial advice. No live trading.",
        },
        "rules": {
            "trade_eligible": [
                "score >= 85",
                "price >= 3",
                "relative_volume >= 2",
                "price above VWAP",
                "vwap_distance_pct <= 6",
                "risk_reward >= 2",
                "data quality is GOOD",
            ],
            "wait_for_pullback": [
                "good score but price too extended above VWAP",
                "dashboard only",
                "no auto-buy",
            ],
            "alert_only": [
                "interesting setup but missing at least one key confirmation",
                "dashboard only",
                "no auto-buy",
            ],
            "watch_only": [
                "early or incomplete setup",
                "dashboard only",
                "no auto-buy",
            ],
            "no_trade": [
                "blocked by risk, data, price, volume, trend, or score rules",
                "no auto-buy",
            ],
        },
    }

    return payload


def export_free_scanner() -> Dict[str, Any]:
    payload = build_payload()

    health = {
        "schema_version": "scanner_health_v1",
        "generated_at": payload["generated_at"],
        "status": payload["status"],
        "scanner": "free_scanner_normalizer_v1",
        "sources_used": payload["sources_used"],
        "used_placeholders": payload["used_placeholders"],
        "candidate_count": payload["counts"]["total"],
        "real_rows": payload["counts"]["real_rows"],
        "placeholder_rows": payload["counts"]["placeholder_rows"],
        "trade_eligible_count": payload["counts"]["trade_eligible"],
        "order_submission": False,
        "paper_only": True,
        "notes": [
            "Package 1A normalizes existing scanner/candidate data only.",
            "Package 1A does not pull live Alpaca data.",
            "Package 1A does not submit paper or live orders.",
            "If used_placeholders is true, no real candidate data was found.",
        ],
    }

    _write_json(OUTPUT_PATH, payload)
    _write_json(HEALTH_PATH, health)

    return {
        "status": "PASS",
        "output_path": str(OUTPUT_PATH),
        "health_path": str(HEALTH_PATH),
        "row_count": payload["counts"]["total"],
        "real_rows": payload["counts"]["real_rows"],
        "trade_eligible_count": payload["counts"]["trade_eligible"],
        "used_placeholders": payload["used_placeholders"],
    }


def main() -> None:
    print(json.dumps(export_free_scanner(), indent=2))


if __name__ == "__main__":
    main()
