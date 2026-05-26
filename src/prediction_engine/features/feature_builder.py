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

    def _extract_base_features(self, row: dict[str, Any]) -> dict[str, Any]:
        ticker = safe_str(row.get("ticker") or row.get("symbol")).upper()
        source = safe_str(
            row.get("source")
            or row.get("feed")
            or row.get("data_source")
            or row.get("alpaca_feed"),
            "UNKNOWN",
        ).upper()
        catalyst_flag = bool(row.get("catalyst_flag") or row.get("has_catalyst") or False)
        return {"ticker": ticker, "source": source, "catalyst_flag": catalyst_flag}

    def _extract_price_features(self, row: dict[str, Any]) -> dict[str, Any]:
        price = safe_float(row.get("price") or row.get("last_price") or row.get("close") or row.get("mark"))
        prev_close = safe_float(row.get("prev_close") or row.get("previous_close"))
        vwap = safe_float(row.get("vwap"))

        day_move_pct = safe_float(row.get("day_move_pct"))
        if day_move_pct == 0 and price > 0 and prev_close > 0:
            day_move_pct = pct_change(price, prev_close)

        vwap_distance_pct = safe_float(row.get("vwap_distance_pct"))
        if vwap_distance_pct == 0 and price > 0 and vwap > 0:
            vwap_distance_pct = pct_change(price, vwap)

        return {
            "price": price,
            "prev_close": prev_close,
            "vwap": vwap,
            "day_move_pct": day_move_pct,
            "vwap_distance_pct": vwap_distance_pct,
        }

    def _extract_volume_features(self, row: dict[str, Any], price: float) -> dict[str, Any]:
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

        return {
            "relative_volume": relative_volume,
            "volume": volume,
            "avg_volume": avg_volume,
            "dollar_volume": dollar_volume,
        }

    def _extract_quote_features(self, row: dict[str, Any]) -> dict[str, Any]:
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

        return {
            "spread_pct": spread_pct,
            "quote_age_sec": quote_age_sec,
        }

    def _extract_momentum_features(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "momentum_1m": safe_float(row.get("momentum_1m") or row.get("mom1_pct")),
            "momentum_3m": safe_float(row.get("momentum_3m") or row.get("mom3_pct")),
            "momentum_5m": safe_float(row.get("momentum_5m") or row.get("mom5_pct")),
        }

    def _extract_intraday_features(self, row: dict[str, Any], price: float) -> dict[str, Any]:
        high_of_day = safe_float(row.get("high_of_day") or row.get("hod") or row.get("high"))
        low_of_day = safe_float(row.get("low_of_day") or row.get("lod") or row.get("low"))

        high_of_day_distance_pct = 0.0
        if price > 0 and high_of_day > 0:
            high_of_day_distance_pct = pct_change(price, high_of_day)

        intraday_range_pct = 0.0
        if high_of_day > 0 and low_of_day > 0:
            intraday_range_pct = pct_change(high_of_day, low_of_day)

        return {
            "high_of_day": high_of_day,
            "low_of_day": low_of_day,
            "high_of_day_distance_pct": high_of_day_distance_pct,
            "intraday_range_pct": intraday_range_pct,
            "pullback_depth_pct": safe_float(row.get("pullback_depth_pct")),
            "volume_reexpansion": safe_float(row.get("volume_reexpansion") or row.get("volume_reexpansion_ratio"), 0.0),
            "candle_strength": safe_float(row.get("candle_strength"), 0.0),
        }

    def _assess_quality(self, features: dict[str, Any]) -> dict[str, Any]:
        blockers: list[str] = []
        warnings: list[str] = []

        if not features["ticker"]:
            blockers.append("missing_ticker")

        if features["price"] <= 0:
            blockers.append("missing_price")

        if features["spread_pct"] < 0:
            warnings.append("spread_missing")

        if features["quote_age_sec"] < 0:
            warnings.append("quote_age_missing")

        if features["source"] == "UNKNOWN":
            warnings.append("source_unknown")

        return {
            "feature_quality_pass": len(blockers) == 0,
            "feature_blockers": blockers,
            "feature_warnings": warnings,
        }

    def build_row(self, row: dict[str, Any]) -> dict[str, Any]:
        f = {}
        f.update(self._extract_base_features(row))
        f.update(self._extract_price_features(row))
        f.update(self._extract_volume_features(row, f["price"]))
        f.update(self._extract_quote_features(row))
        f.update(self._extract_momentum_features(row))
        f.update(self._extract_intraday_features(row, f["price"]))
        f.update(self._assess_quality(f))

        return {
            "ticker": f["ticker"],
            "price": round(f["price"], 4),
            "prev_close": round(f["prev_close"], 4),
            "day_move_pct": round(f["day_move_pct"], 4),
            "vwap": round(f["vwap"], 4),
            "vwap_distance_pct": round(f["vwap_distance_pct"], 4),
            "relative_volume": round(f["relative_volume"], 4),
            "volume": round(f["volume"], 2),
            "avg_volume": round(f["avg_volume"], 2),
            "dollar_volume": round(f["dollar_volume"], 2),
            "spread_pct": round(f["spread_pct"], 5),
            "quote_age_sec": round(f["quote_age_sec"], 2),
            "momentum_1m": round(f["momentum_1m"], 4),
            "momentum_3m": round(f["momentum_3m"], 4),
            "momentum_5m": round(f["momentum_5m"], 4),
            "high_of_day": round(f["high_of_day"], 4),
            "low_of_day": round(f["low_of_day"], 4),
            "high_of_day_distance_pct": round(f["high_of_day_distance_pct"], 4),
            "intraday_range_pct": round(f["intraday_range_pct"], 4),
            "pullback_depth_pct": round(f["pullback_depth_pct"], 4),
            "volume_reexpansion": round(f["volume_reexpansion"], 4),
            "candle_strength": round(f["candle_strength"], 4),
            "catalyst_flag": f["catalyst_flag"],
            "source": f["source"],
            "feature_quality_pass": f["feature_quality_pass"],
            "feature_blockers": f["feature_blockers"],
            "feature_warnings": f["feature_warnings"],
            "order_submission": False,
            "live_trading": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
        }

    def build(self, rows: list[dict[str, Any]], limit: int = 250) -> list[dict[str, Any]]:
        out = [self.build_row(row) for row in rows if isinstance(row, dict)]
        out.sort(key=lambda r: (r.get("feature_quality_pass") is True, safe_float(r.get("day_move_pct")), safe_float(r.get("relative_volume"))), reverse=True)
        return out[:limit]
