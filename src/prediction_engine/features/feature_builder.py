from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        x = float(value)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except Exception:
        return default


def safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def pct_change(current: float, base: float) -> float:
    if base <= 0:
        return 0.0
    return ((current - base) / base) * 100.0


class FeatureBuilder:
    """
    Research-only feature builder.

    It creates normalized feature rows.
    It does not submit orders.
    It does not enable live trading.
    """

    def build_row(self, row: dict[str, Any]) -> dict[str, Any]:
        ticker = safe_str(row.get("ticker") or row.get("symbol")).upper()

        price = safe_float(row.get("price") or row.get("last_price") or row.get("close") or row.get("mark"))
        prev_close = safe_float(row.get("prev_close") or row.get("previous_close"))
        vwap = safe_float(row.get("vwap"))

        day_move_pct = safe_float(row.get("day_move_pct"))
        if day_move_pct == 0 and price > 0 and prev_close > 0:
            day_move_pct = pct_change(price, prev_close)

        vwap_distance_pct = safe_float(row.get("vwap_distance_pct"))
        if vwap_distance_pct == 0 and price > 0 and vwap > 0:
            vwap_distance_pct = pct_change(price, vwap)

        relative_volume = safe_float(
            row.get("relative_volume")
            or row.get("rel_vol")
            or row.get("rvol")
            or row.get("time_slot_rvol"),
            1.0,
        )

        volume = safe_float(row.get("volume") or row.get("bar_volume"))
        avg_volume = safe_float(row.get("avg_volume") or row.get("average_volume"))
        dollar_volume = safe_float(row.get("dollar_volume"))

        if dollar_volume <= 0 and volume > 0 and price > 0:
            dollar_volume = volume * price

        bid = safe_float(row.get("bid"))
        ask = safe_float(row.get("ask"))
        spread_pct = safe_float(row.get("spread_pct"), -1.0)

        if spread_pct < 0 and bid > 0 and ask > 0 and ask >= bid:
            mid = (bid + ask) / 2
            spread_pct = ((ask - bid) / mid) if mid > 0 else -1.0

        quote_age_sec = safe_float(
            row.get("quote_age_sec")
            or row.get("quote_age_seconds")
            or row.get("quote_age")
            or row.get("age_sec"),
            -1.0,
        )

        momentum_1m = safe_float(row.get("momentum_1m") or row.get("mom1_pct"))
        momentum_3m = safe_float(row.get("momentum_3m") or row.get("mom3_pct"))
        momentum_5m = safe_float(row.get("momentum_5m") or row.get("mom5_pct"))

        high_of_day = safe_float(row.get("high_of_day") or row.get("hod") or row.get("high"))
        low_of_day = safe_float(row.get("low_of_day") or row.get("lod") or row.get("low"))

        high_of_day_distance_pct = 0.0
        if price > 0 and high_of_day > 0:
            high_of_day_distance_pct = pct_change(price, high_of_day)

        intraday_range_pct = 0.0
        if high_of_day > 0 and low_of_day > 0:
            intraday_range_pct = pct_change(high_of_day, low_of_day)

        pullback_depth_pct = safe_float(row.get("pullback_depth_pct"))
        volume_reexpansion = safe_float(row.get("volume_reexpansion") or row.get("volume_reexpansion_ratio"), 0.0)
        candle_strength = safe_float(row.get("candle_strength"), 0.0)
        catalyst_flag = bool(row.get("catalyst_flag") or row.get("has_catalyst") or False)

        source = safe_str(
            row.get("source")
            or row.get("feed")
            or row.get("data_source")
            or row.get("alpaca_feed"),
            "UNKNOWN",
        ).upper()

        blockers: list[str] = []
        warnings: list[str] = []

        if not ticker:
            blockers.append("missing_ticker")

        if price <= 0:
            blockers.append("missing_price")

        if spread_pct < 0:
            warnings.append("spread_missing")

        if quote_age_sec < 0:
            warnings.append("quote_age_missing")

        if source == "UNKNOWN":
            warnings.append("source_unknown")

        feature_quality_pass = len(blockers) == 0

        return {
            "ticker": ticker,
            "price": round(price, 4),
            "prev_close": round(prev_close, 4),
            "day_move_pct": round(day_move_pct, 4),
            "vwap": round(vwap, 4),
            "vwap_distance_pct": round(vwap_distance_pct, 4),
            "relative_volume": round(relative_volume, 4),
            "volume": round(volume, 2),
            "avg_volume": round(avg_volume, 2),
            "dollar_volume": round(dollar_volume, 2),
            "spread_pct": round(spread_pct, 5),
            "quote_age_sec": round(quote_age_sec, 2),
            "momentum_1m": round(momentum_1m, 4),
            "momentum_3m": round(momentum_3m, 4),
            "momentum_5m": round(momentum_5m, 4),
            "high_of_day": round(high_of_day, 4),
            "low_of_day": round(low_of_day, 4),
            "high_of_day_distance_pct": round(high_of_day_distance_pct, 4),
            "intraday_range_pct": round(intraday_range_pct, 4),
            "pullback_depth_pct": round(pullback_depth_pct, 4),
            "volume_reexpansion": round(volume_reexpansion, 4),
            "candle_strength": round(candle_strength, 4),
            "catalyst_flag": catalyst_flag,
            "source": source,
            "feature_quality_pass": feature_quality_pass,
            "feature_blockers": blockers,
            "feature_warnings": warnings,
            "order_submission": False,
            "live_trading": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
        }

    def build(self, rows: list[dict[str, Any]], limit: int = 250) -> list[dict[str, Any]]:
        out = [self.build_row(row) for row in rows if isinstance(row, dict)]
        out.sort(key=lambda r: (r.get("feature_quality_pass") is True, safe_float(r.get("day_move_pct")), safe_float(r.get("relative_volume"))), reverse=True)
        return out[:limit]
