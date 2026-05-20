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


class EntryQualityScorerV3:
    """
    Research-only entry quality scorer.

    Answers:
    Is this a good entry right now?

    Does not submit orders.
    Does not enable paper trading.
    Does not enable live trading.
    """

    def score_row(self, row: dict[str, Any]) -> dict[str, Any]:
        ticker = str(row.get("ticker") or row.get("symbol") or "").upper().strip()

        price = safe_float(row.get("price"))
        vwap_dist = safe_float(row.get("vwap_distance_pct"))
        pullback_depth = safe_float(row.get("pullback_depth_pct"))
        volume_reexpansion = safe_float(row.get("volume_reexpansion"))
        spread = safe_float(row.get("spread_pct"), -1.0)
        quote_age = safe_float(row.get("quote_age_sec"), -1.0)
        mom1 = safe_float(row.get("momentum_1m"))
        mom3 = safe_float(row.get("momentum_3m"))
        mom5 = safe_float(row.get("momentum_5m"))
        candle_strength = safe_float(row.get("candle_strength"))
        hod_dist = safe_float(row.get("high_of_day_distance_pct"))

        blockers: list[str] = []
        warnings: list[str] = []

        if not ticker:
            blockers.append("missing_ticker")

        if price <= 0:
            blockers.append("missing_price")

        # VWAP quality.
        if 0 <= vwap_dist <= 3:
            vwap_score = 20.0
        elif 3 < vwap_dist <= 6:
            vwap_score = 13.0
            warnings.append("slightly_extended_from_vwap")
        elif vwap_dist < 0:
            vwap_score = 4.0
            warnings.append("below_vwap")
        else:
            vwap_score = 6.0
            warnings.append("too_extended_from_vwap")

        # Pullback quality. If missing, neutral-low score.
        if -1.2 <= pullback_depth <= -0.10:
            pullback_score = 20.0
        elif -2.5 <= pullback_depth < -1.2:
            pullback_score = 12.0
            warnings.append("deep_pullback")
        elif pullback_depth == 0:
            pullback_score = 8.0
            warnings.append("pullback_depth_missing")
        elif pullback_depth > 0:
            pullback_score = 5.0
            warnings.append("no_pullback_chase_risk")
        else:
            pullback_score = 8.0

        # Reclaim / momentum quality.
        momentum_sum = mom1 + mom3 + mom5
        reclaim_strength_score = clamp((momentum_sum / 4.0) * 15.0, 0, 15)

        # Volume re-expansion quality.
        if volume_reexpansion >= 1.5:
            volume_reexpansion_score = 15.0
        elif volume_reexpansion >= 1.1:
            volume_reexpansion_score = 10.0
        elif volume_reexpansion > 0:
            volume_reexpansion_score = 6.0
            warnings.append("weak_volume_reexpansion")
        else:
            volume_reexpansion_score = 5.0
            warnings.append("volume_reexpansion_missing")

        # Spread quality.
        if 0 <= spread <= 0.006:
            spread_score = 10.0
        elif 0.006 < spread <= 0.012:
            spread_score = 7.0
        elif 0.012 < spread <= 0.025:
            spread_score = 4.0
            warnings.append("wide_spread")
        elif spread < 0:
            spread_score = 5.0
            warnings.append("spread_missing")
        else:
            spread_score = 0.0
            blockers.append("spread_too_wide")

        # Quote freshness.
        if 0 <= quote_age <= 10:
            quote_score = 10.0
        elif 10 < quote_age <= 30:
            quote_score = 7.0
        elif 30 < quote_age <= 60:
            quote_score = 3.0
            warnings.append("quote_aging")
        elif quote_age < 0:
            quote_score = 5.0
            warnings.append("quote_age_missing")
        else:
            quote_score = 0.0
            blockers.append("quote_stale")

        # Risk/reward positioning near HOD.
        if -3 <= hod_dist <= 0:
            rr_score = 10.0
        elif -6 <= hod_dist < -3:
            rr_score = 6.0
        elif hod_dist > 0:
            rr_score = 5.0
            warnings.append("above_recorded_hod_check_data")
        else:
            rr_score = 4.0
            warnings.append("far_from_hod")

        entry_quality_score = (
            vwap_score
            + pullback_score
            + reclaim_strength_score
            + volume_reexpansion_score
            + spread_score
            + quote_score
            + rr_score
        )

        # Candle strength can slightly improve quality, but cannot save bad data.
        candle_bonus = clamp(candle_strength, 0, 5)
        entry_quality_score = clamp(entry_quality_score + candle_bonus)

        if entry_quality_score >= 78 and not blockers:
            status = "ENTRY_CLEAN"
        elif entry_quality_score >= 62 and not blockers:
            status = "ENTRY_WAIT"
        elif not blockers:
            status = "ENTRY_WEAK"
        else:
            status = "ENTRY_BLOCKED"

        return {
            **row,
            "entry_quality_v3": round(entry_quality_score, 4),
            "entry_quality_status_v3": status,
            "entry_quality_components_v3": {
                "vwap_score": round(vwap_score, 4),
                "pullback_score": round(pullback_score, 4),
                "reclaim_strength_score": round(reclaim_strength_score, 4),
                "volume_reexpansion_score": round(volume_reexpansion_score, 4),
                "spread_score": round(spread_score, 4),
                "quote_score": round(quote_score, 4),
                "risk_reward_score": round(rr_score, 4),
                "candle_bonus": round(candle_bonus, 4),
            },
            "entry_quality_blockers_v3": blockers,
            "entry_quality_warnings_v3": warnings,
            "order_submission": False,
            "live_trading": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
        }

    def score(self, rows: list[dict[str, Any]], limit: int = 250) -> list[dict[str, Any]]:
        out = [self.score_row(row) for row in rows if isinstance(row, dict)]
        out.sort(key=lambda r: safe_float(r.get("entry_quality_v3")), reverse=True)
        return out[:limit]
