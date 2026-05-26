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

        vwap_score = self._calc_vwap_score(vwap_dist, warnings)
        pullback_score = self._calc_pullback_score(pullback_depth, warnings)
        reclaim_strength_score = self._calc_reclaim_strength_score(mom1, mom3, mom5)
        volume_reexpansion_score = self._calc_volume_reexpansion_score(volume_reexpansion, warnings)
        spread_score = self._calc_spread_score(spread, warnings, blockers)
        quote_score = self._calc_quote_score(quote_age, warnings, blockers)
        rr_score = self._calc_rr_score(hod_dist, warnings)

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

    def _calc_vwap_score(self, vwap_dist: float, warnings: list[str]) -> float:
        if 0 <= vwap_dist <= 3:
            return 20.0
        if 3 < vwap_dist <= 6:
            warnings.append("slightly_extended_from_vwap")
            return 13.0
        if vwap_dist < 0:
            warnings.append("below_vwap")
            return 4.0
        warnings.append("too_extended_from_vwap")
        return 6.0

    def _calc_pullback_score(self, pullback_depth: float, warnings: list[str]) -> float:
        if -1.2 <= pullback_depth <= -0.10:
            return 20.0
        if -2.5 <= pullback_depth < -1.2:
            warnings.append("deep_pullback")
            return 12.0
        if pullback_depth == 0:
            warnings.append("pullback_depth_missing")
            return 8.0
        if pullback_depth > 0:
            warnings.append("no_pullback_chase_risk")
            return 5.0
        return 8.0

    def _calc_reclaim_strength_score(self, mom1: float, mom3: float, mom5: float) -> float:
        momentum_sum = mom1 + mom3 + mom5
        return clamp((momentum_sum / 4.0) * 15.0, 0, 15)

    def _calc_volume_reexpansion_score(self, volume_reexpansion: float, warnings: list[str]) -> float:
        if volume_reexpansion >= 1.5:
            return 15.0
        if volume_reexpansion >= 1.1:
            return 10.0
        if volume_reexpansion > 0:
            warnings.append("weak_volume_reexpansion")
            return 6.0
        warnings.append("volume_reexpansion_missing")
        return 5.0

    def _calc_spread_score(self, spread: float, warnings: list[str], blockers: list[str]) -> float:
        if 0 <= spread <= 0.006:
            return 10.0
        if 0.006 < spread <= 0.012:
            return 7.0
        if 0.012 < spread <= 0.025:
            warnings.append("wide_spread")
            return 4.0
        if spread < 0:
            warnings.append("spread_missing")
            return 5.0
        blockers.append("spread_too_wide")
        return 0.0

    def _calc_quote_score(self, quote_age: float, warnings: list[str], blockers: list[str]) -> float:
        if 0 <= quote_age <= 10:
            return 10.0
        if 10 < quote_age <= 30:
            return 7.0
        if 30 < quote_age <= 60:
            warnings.append("quote_aging")
            return 3.0
        if quote_age < 0:
            warnings.append("quote_age_missing")
            return 5.0
        blockers.append("quote_stale")
        return 0.0

    def _calc_rr_score(self, hod_dist: float, warnings: list[str]) -> float:
        if -3 <= hod_dist <= 0:
            return 10.0
        if -6 <= hod_dist < -3:
            return 6.0
        if hod_dist > 0:
            warnings.append("above_recorded_hod_check_data")
            return 5.0
        warnings.append("far_from_hod")
        return 4.0

    def score(self, rows: list[dict[str, Any]], limit: int = 250) -> list[dict[str, Any]]:
        out = [self.score_row(row) for row in rows if isinstance(row, dict)]
        out.sort(key=lambda r: safe_float(r.get("entry_quality_v3")), reverse=True)
        return out[:limit]
