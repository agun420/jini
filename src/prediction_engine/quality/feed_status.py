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


def row_price(row: dict[str, Any]) -> float:
    for key in ("price", "last_price", "close", "last", "mark"):
        x = safe_float(row.get(key), 0.0)
        if x > 0:
            return x
    return 0.0


def row_spread_pct(row: dict[str, Any]) -> float:
    spread = safe_float(row.get("spread_pct"), -1.0)
    if spread >= 0:
        return spread

    bid = safe_float(row.get("bid"), 0.0)
    ask = safe_float(row.get("ask"), 0.0)

    if bid > 0 and ask > 0 and ask >= bid:
        mid = (bid + ask) / 2
        if mid > 0:
            return (ask - bid) / mid

    return -1.0


class FeedStatusEvaluator:
    """
    Data quality evaluator.

    Research/safety only.
    Does not submit orders.
    Does not enable live trading.
    """

    def __init__(
        self,
        max_quote_age_sec: int = 30,
        max_spread_pct: float = 0.025,
    ):
        self.max_quote_age_sec = max_quote_age_sec
        self.max_spread_pct = max_spread_pct

    def evaluate_row(self, row: dict[str, Any]) -> dict[str, Any]:
        symbol = safe_str(row.get("ticker") or row.get("symbol"), "UNKNOWN").upper()
        price = row_price(row)
        spread_pct = row_spread_pct(row)

        quote_age = safe_float(
            row.get("quote_age_sec")
            or row.get("quote_age_seconds")
            or row.get("quote_age")
            or row.get("age_sec"),
            -1.0,
        )

        source = safe_str(
            row.get("source")
            or row.get("feed")
            or row.get("data_source")
            or row.get("scanner_source")
            or row.get("alpaca_feed"),
            "UNKNOWN",
        ).upper()

        data_status = safe_str(
            row.get("scanner_data_status")
            or row.get("data_feed_guard_status")
            or row.get("data_status"),
            "",
        ).upper()

        blockers: list[str] = []
        warnings: list[str] = []

        if price <= 0:
            blockers.append("missing_or_zero_price")

        if spread_pct < 0:
            warnings.append("spread_missing")
        elif spread_pct > self.max_spread_pct:
            blockers.append("spread_too_wide")

        if quote_age < 0:
            warnings.append("quote_age_missing")
        elif quote_age > self.max_quote_age_sec:
            blockers.append("quote_stale")

        if source in {"MOCK", "TEST", "FALLBACK"}:
            blockers.append("untrusted_feed_source")

        if "FAIL" in data_status:
            blockers.append("upstream_data_status_fail")

        if source == "UNKNOWN":
            warnings.append("feed_source_unknown")

        can_use_for_buy_alert = len(blockers) == 0

        return {
            "ticker": symbol,
            "price": price,
            "spread_pct": spread_pct,
            "quote_age_sec": quote_age,
            "feed_source": source,
            "upstream_data_status": data_status or "UNKNOWN",
            "can_use_for_buy_alert": can_use_for_buy_alert,
            "can_use_for_paper_order": False,
            "can_use_for_live_order": False,
            "blockers": blockers,
            "warnings": warnings,
            "order_submission": False,
            "live_trading": False,
        }
