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


def pct_change(current: float, previous: float) -> float:
    if previous <= 0:
        return 0.0
    return ((current - previous) / previous) * 100.0


class TopGainerOpportunityScanner:
    """
    Research-only top gainer scanner.

    It ranks opportunities only.
    It does not submit orders.
    It does not enable live trading.
    """

    def __init__(
        self,
        price_min: float = 1.50,
        price_max: float = 75.00,
        day_move_min_pct: float = 3.0,
        rvol_min: float = 1.0,
        spread_max_pct: float = 0.025,
        quote_age_max_sec: float = 60.0,
    ):
        self.price_min = price_min
        self.price_max = price_max
        self.day_move_min_pct = day_move_min_pct
        self.rvol_min = rvol_min
        self.spread_max_pct = spread_max_pct
        self.quote_age_max_sec = quote_age_max_sec

    def normalize_row(self, row: dict[str, Any]) -> dict[str, Any]:
        ticker = safe_str(row.get("ticker") or row.get("symbol")).upper()

        price = 0.0
        for key in ("price", "last_price", "close", "last", "mark"):
            price = safe_float(row.get(key), 0.0)
            if price > 0:
                break

        prev_close = safe_float(row.get("prev_close") or row.get("previous_close"), 0.0)
        day_move_pct = safe_float(row.get("day_move_pct"), pct_change(price, prev_close))

        rvol = safe_float(
            row.get("relative_volume")
            or row.get("rel_vol")
            or row.get("rvol")
            or row.get("time_slot_rvol"),
            1.0,
        )

        spread_pct = safe_float(row.get("spread_pct"), -1.0)
        bid = safe_float(row.get("bid"), 0.0)
        ask = safe_float(row.get("ask"), 0.0)

        if spread_pct < 0 and bid > 0 and ask > 0 and ask >= bid:
            mid = (bid + ask) / 2
            spread_pct = (ask - bid) / mid if mid > 0 else -1.0

        quote_age_sec = safe_float(
            row.get("quote_age_sec")
            or row.get("quote_age_seconds")
            or row.get("quote_age")
            or row.get("age_sec"),
            -1.0,
        )

        dollar_volume = safe_float(row.get("dollar_volume"), 0.0)
        volume = safe_float(row.get("volume"), 0.0)

        if dollar_volume <= 0 and volume > 0 and price > 0:
            dollar_volume = volume * price

        vwap = safe_float(row.get("vwap"), 0.0)
        vwap_distance_pct = safe_float(row.get("vwap_distance_pct"), 0.0)

        if vwap_distance_pct == 0 and vwap > 0 and price > 0:
            vwap_distance_pct = pct_change(price, vwap)

        momentum_1m = safe_float(row.get("momentum_1m") or row.get("mom1_pct"), 0.0)
        momentum_5m = safe_float(row.get("momentum_5m") or row.get("mom5_pct"), 0.0)

        source = safe_str(
            row.get("source")
            or row.get("feed")
            or row.get("data_source")
            or row.get("alpaca_feed"),
            "UNKNOWN",
        ).upper()

        return {
            "ticker": ticker,
            "price": round(price, 4),
            "prev_close": round(prev_close, 4),
            "day_move_pct": round(day_move_pct, 4),
            "relative_volume": round(rvol, 4),
            "dollar_volume": round(dollar_volume, 2),
            "spread_pct": round(spread_pct, 5),
            "quote_age_sec": round(quote_age_sec, 2),
            "vwap": round(vwap, 4),
            "vwap_distance_pct": round(vwap_distance_pct, 4),
            "momentum_1m": round(momentum_1m, 4),
            "momentum_5m": round(momentum_5m, 4),
            "source": source,
            "raw": row,
        }

    def score_opportunity(self, row: dict[str, Any]) -> dict[str, Any]:
        blockers: list[str] = []
        warnings: list[str] = []

        price = safe_float(row.get("price"))
        day_move = safe_float(row.get("day_move_pct"))
        rvol = safe_float(row.get("relative_volume"))
        spread = safe_float(row.get("spread_pct"), -1.0)
        quote_age = safe_float(row.get("quote_age_sec"), -1.0)
        dollar_volume = safe_float(row.get("dollar_volume"))
        vwap_dist = safe_float(row.get("vwap_distance_pct"))
        mom1 = safe_float(row.get("momentum_1m"))
        mom5 = safe_float(row.get("momentum_5m"))

        if not row.get("ticker"):
            blockers.append("missing_ticker")

        if price < self.price_min or price > self.price_max:
            blockers.append("price_outside_scanner_range")

        if day_move < self.day_move_min_pct:
            warnings.append("day_move_below_primary_threshold")

        if rvol < self.rvol_min:
            warnings.append("relative_volume_below_primary_threshold")

        if spread < 0:
            warnings.append("spread_missing")
        elif spread > self.spread_max_pct:
            blockers.append("spread_too_wide")

        if quote_age < 0:
            warnings.append("quote_age_missing")
        elif quote_age > self.quote_age_max_sec:
            blockers.append("quote_stale")

        if dollar_volume <= 0:
            warnings.append("dollar_volume_missing")

        # Score is intentionally simple. Later packages will replace this with the feature builder + scoring model.
        move_score = min(max(day_move, 0), 30) / 30 * 30
        rvol_score = min(max(rvol, 0), 5) / 5 * 25
        liquidity_score = min(max(dollar_volume, 0), 25_000_000) / 25_000_000 * 15
        vwap_score = 10 if vwap_dist >= 0 else 0
        momentum_score = min(max(mom1 + mom5, 0), 5) / 5 * 15

        spread_penalty = 0
        if spread > 0:
            spread_penalty = min(spread / self.spread_max_pct, 2) * 5

        quote_penalty = 0
        if quote_age > 0:
            quote_penalty = min(quote_age / self.quote_age_max_sec, 2) * 5

        opportunity_score = move_score + rvol_score + liquidity_score + vwap_score + momentum_score - spread_penalty - quote_penalty
        opportunity_score = max(0.0, min(100.0, opportunity_score))

        status = "OPPORTUNITY_CANDIDATE" if not blockers else "BLOCKED_BY_SCANNER"

        return {
            **{k: v for k, v in row.items() if k != "raw"},
            "opportunity_score": round(opportunity_score, 4),
            "scanner_status": status,
            "scanner_blockers": blockers,
            "scanner_warnings": warnings,
            "order_submission": False,
            "live_trading": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
        }

    def scan(self, rows: list[dict[str, Any]], limit: int = 100) -> list[dict[str, Any]]:
        normalized = [self.normalize_row(row) for row in rows if isinstance(row, dict)]
        scored = [self.score_opportunity(row) for row in normalized]
        scored.sort(key=lambda r: safe_float(r.get("opportunity_score")), reverse=True)
        return scored[:limit]
