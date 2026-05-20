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


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


class DangerScoreScorerV3:
    """
    Research-only danger scorer.

    Answers:
    What can go wrong?

    Higher score = more dangerous.

    Does not submit orders.
    Does not enable paper trading.
    Does not enable live trading.
    """

    def score_row(self, row: dict[str, Any]) -> dict[str, Any]:
        ticker = str(row.get("ticker") or row.get("symbol") or "").upper().strip()

        price = safe_float(row.get("price"))
        vwap_dist = safe_float(row.get("vwap_distance_pct"))
        spread = safe_float(row.get("spread_pct"), -1.0)
        quote_age = safe_float(row.get("quote_age_sec"), -1.0)
        day_move = safe_float(row.get("day_move_pct"))
        rvol = safe_float(row.get("relative_volume"), 1.0)
        mom1 = safe_float(row.get("momentum_1m"))
        mom3 = safe_float(row.get("momentum_3m"))
        mom5 = safe_float(row.get("momentum_5m"))
        hod_dist = safe_float(row.get("high_of_day_distance_pct"))
        pullback_depth = safe_float(row.get("pullback_depth_pct"))
        volume_reexpansion = safe_float(row.get("volume_reexpansion"))
        candle_strength = safe_float(row.get("candle_strength"))
        catalyst = bool(row.get("catalyst_flag"))

        blockers: list[str] = []
        warnings: list[str] = []

        if not ticker:
            blockers.append("missing_ticker")

        if price <= 0:
            blockers.append("missing_price")

        # Extension penalty.
        if vwap_dist <= 0:
            extension_penalty = 8.0
            warnings.append("below_or_at_vwap")
        elif 0 < vwap_dist <= 4:
            extension_penalty = 2.0
        elif 4 < vwap_dist <= 8:
            extension_penalty = 10.0
            warnings.append("extended_from_vwap")
        else:
            extension_penalty = 18.0
            warnings.append("very_extended_from_vwap")

        # Spread penalty.
        if spread < 0:
            spread_penalty = 8.0
            warnings.append("spread_missing")
        elif spread <= 0.006:
            spread_penalty = 1.0
        elif spread <= 0.012:
            spread_penalty = 5.0
        elif spread <= 0.025:
            spread_penalty = 12.0
            warnings.append("wide_spread")
        else:
            spread_penalty = 22.0
            blockers.append("spread_too_wide")

        # Quote staleness.
        if quote_age < 0:
            stale_quote_penalty = 8.0
            warnings.append("quote_age_missing")
        elif quote_age <= 10:
            stale_quote_penalty = 1.0
        elif quote_age <= 30:
            stale_quote_penalty = 5.0
        elif quote_age <= 60:
            stale_quote_penalty = 12.0
            warnings.append("quote_aging")
        else:
            stale_quote_penalty = 22.0
            blockers.append("quote_stale")

        # Exhaustion penalty.
        momentum_sum = mom1 + mom3 + mom5
        if day_move >= 20 and momentum_sum <= 0:
            exhaustion_penalty = 14.0
            warnings.append("large_move_with_weak_momentum")
        elif day_move >= 12 and rvol < 1.2:
            exhaustion_penalty = 10.0
            warnings.append("large_move_without_rvol_support")
        elif momentum_sum < -1:
            exhaustion_penalty = 12.0
            warnings.append("negative_short_term_momentum")
        else:
            exhaustion_penalty = 3.0

        # Failed breakout / HOD distance.
        if hod_dist < -8:
            failed_breakout_penalty = 12.0
            warnings.append("far_below_high_of_day")
        elif -8 <= hod_dist < -4:
            failed_breakout_penalty = 8.0
        elif -4 <= hod_dist <= 0:
            failed_breakout_penalty = 2.0
        elif hod_dist > 0:
            failed_breakout_penalty = 6.0
            warnings.append("above_recorded_hod_check_data")
        else:
            failed_breakout_penalty = 5.0

        # Pullback risk.
        if pullback_depth < -3:
            pullback_penalty = 10.0
            warnings.append("pullback_too_deep")
        elif -3 <= pullback_depth <= -0.1:
            pullback_penalty = 2.0
        elif pullback_depth == 0:
            pullback_penalty = 6.0
            warnings.append("pullback_missing")
        else:
            pullback_penalty = 8.0
            warnings.append("no_pullback_chase_risk")

        # Volume failure.
        if volume_reexpansion <= 0:
            volume_failure_penalty = 7.0
            warnings.append("volume_reexpansion_missing")
        elif volume_reexpansion < 1.0:
            volume_failure_penalty = 9.0
            warnings.append("weak_volume_reexpansion")
        elif volume_reexpansion < 1.25:
            volume_failure_penalty = 5.0
        else:
            volume_failure_penalty = 2.0

        # No catalyst penalty.
        no_catalyst_penalty = 0.0 if catalyst else 6.0
        if not catalyst:
            warnings.append("no_catalyst_flag")

        # Candle weakness.
        if candle_strength <= 0:
            candle_penalty = 5.0
        elif candle_strength < 0.35:
            candle_penalty = 4.0
        elif candle_strength < 0.65:
            candle_penalty = 2.0
        else:
            candle_penalty = 0.0

        danger_score = (
            extension_penalty
            + spread_penalty
            + stale_quote_penalty
            + exhaustion_penalty
            + failed_breakout_penalty
            + pullback_penalty
            + volume_failure_penalty
            + no_catalyst_penalty
            + candle_penalty
        )

        danger_score = clamp(danger_score)

        if blockers:
            status = "DANGER_BLOCKED"
        elif danger_score <= 25:
            status = "DANGER_LOW"
        elif danger_score <= 45:
            status = "DANGER_MEDIUM"
        else:
            status = "DANGER_HIGH"

        return {
            **row,
            "danger_score_v3": round(danger_score, 4),
            "danger_status_v3": status,
            "danger_components_v3": {
                "extension_penalty": round(extension_penalty, 4),
                "spread_penalty": round(spread_penalty, 4),
                "stale_quote_penalty": round(stale_quote_penalty, 4),
                "exhaustion_penalty": round(exhaustion_penalty, 4),
                "failed_breakout_penalty": round(failed_breakout_penalty, 4),
                "pullback_penalty": round(pullback_penalty, 4),
                "volume_failure_penalty": round(volume_failure_penalty, 4),
                "no_catalyst_penalty": round(no_catalyst_penalty, 4),
                "candle_penalty": round(candle_penalty, 4),
            },
            "danger_blockers_v3": blockers,
            "danger_warnings_v3": warnings,
            "order_submission": False,
            "live_trading": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
        }

    def score(self, rows: list[dict[str, Any]], limit: int = 250) -> list[dict[str, Any]]:
        out = [self.score_row(row) for row in rows if isinstance(row, dict)]
        out.sort(key=lambda r: safe_float(r.get("danger_score_v3")))
        return out[:limit]
