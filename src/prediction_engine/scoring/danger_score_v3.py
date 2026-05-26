from __future__ import annotations

from typing import Any

from prediction_engine.utils import clamp, safe_float


class DangerScoreScorerV3:
    """
    Research-only danger scorer.

    Answers: What can go wrong?

    Higher score = more dangerous.

    Does not submit orders.
    Does not enable paper trading.
    Does not enable live trading.
    """

    # ── Component penalties ──────────────────────────────────────────────

    def _extension_penalty(self, vwap_dist: float, warnings: list[str]) -> float:
        if vwap_dist <= 0:
            warnings.append("below_or_at_vwap")
            return 8.0
        if vwap_dist <= 4:
            return 2.0
        if vwap_dist <= 8:
            warnings.append("extended_from_vwap")
            return 10.0
        warnings.append("very_extended_from_vwap")
        return 18.0

    def _spread_penalty(self, spread: float, blockers: list[str], warnings: list[str]) -> float:
        if spread < 0:
            warnings.append("spread_missing")
            return 8.0
        if spread <= 0.006:
            return 1.0
        if spread <= 0.012:
            return 5.0
        if spread <= 0.025:
            warnings.append("wide_spread")
            return 12.0
        blockers.append("spread_too_wide")
        return 22.0

    def _stale_quote_penalty(self, quote_age: float, blockers: list[str], warnings: list[str]) -> float:
        if quote_age < 0:
            warnings.append("quote_age_missing")
            return 8.0
        if quote_age <= 10:
            return 1.0
        if quote_age <= 30:
            return 5.0
        if quote_age <= 60:
            warnings.append("quote_aging")
            return 12.0
        blockers.append("quote_stale")
        return 22.0

    def _exhaustion_penalty(self, day_move: float, rvol: float, momentum_sum: float, vwap_dist: float, warnings: list[str]) -> float:
        # Explosive confirmation ONLY valid when entry is also tight to VWAP.
        # Backtest data: CVNA (RVOL 6.9x, vwap 0.39%) +2.89% WIN;
        #                SOFI (RVOL 20x, vwap 0.71-0.85%) -0.53% to -1.13% LOSS.
        # High RVOL extended from VWAP is dangerous, not explosive confirmation.
        if rvol >= 3.0 and momentum_sum > 0 and vwap_dist <= 1.0:
            return 1.0   # truly explosive: tight VWAP + high RVOL + positive momentum
        if rvol >= 3.0 and momentum_sum > 0 and vwap_dist <= 2.0:
            return 5.0   # high RVOL but extended entry — partial danger
        if day_move >= 20 and momentum_sum <= 0:
            warnings.append("large_move_with_weak_momentum")
            return 14.0
        if day_move >= 12 and rvol < 1.2:
            warnings.append("large_move_without_rvol_support")
            return 10.0
        if momentum_sum < -1:
            warnings.append("negative_short_term_momentum")
            return 12.0
        return 3.0

    def _failed_breakout_penalty(self, hod_dist: float, warnings: list[str]) -> float:
        if hod_dist < -8:
            warnings.append("far_below_high_of_day")
            return 12.0
        if hod_dist < -4:
            return 8.0
        if hod_dist <= 0:
            return 2.0
        if hod_dist > 0:
            warnings.append("above_recorded_hod_check_data")
            return 6.0
        return 5.0

    def _pullback_penalty(self, pullback_depth: float, warnings: list[str]) -> float:
        if pullback_depth < -3:
            warnings.append("pullback_too_deep")
            return 10.0
        if pullback_depth <= -0.1:
            return 2.0
        if pullback_depth == 0:
            warnings.append("pullback_missing")
            return 6.0
        warnings.append("no_pullback_chase_risk")
        return 8.0

    def _volume_failure_penalty(self, volume_reexpansion: float, warnings: list[str]) -> float:
        if volume_reexpansion >= 2.0:
            return 0.0   # explosive volume expansion confirmed
        if volume_reexpansion <= 0:
            warnings.append("volume_reexpansion_missing")
            return 7.0
        if volume_reexpansion < 1.0:
            warnings.append("weak_volume_reexpansion")
            return 9.0
        if volume_reexpansion < 1.25:
            return 5.0
        return 2.0

    def _candle_penalty(self, candle_strength: float) -> float:
        if candle_strength <= 0:
            return 5.0
        if candle_strength < 0.35:
            return 4.0
        if candle_strength < 0.65:
            return 2.0
        return 0.0

    # ── Public API ───────────────────────────────────────────────────────

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

        momentum_sum = mom1 + mom3 + mom5

        extension_penalty = self._extension_penalty(vwap_dist, warnings)
        spread_penalty = self._spread_penalty(spread, blockers, warnings)
        stale_quote_penalty = self._stale_quote_penalty(quote_age, blockers, warnings)
        exhaustion_penalty = self._exhaustion_penalty(day_move, rvol, momentum_sum, vwap_dist, warnings)
        failed_breakout_penalty = self._failed_breakout_penalty(hod_dist, warnings)
        pullback_penalty = self._pullback_penalty(pullback_depth, warnings)
        volume_failure_penalty = self._volume_failure_penalty(volume_reexpansion, warnings)
        candle_penalty = self._candle_penalty(candle_strength)

        no_catalyst_penalty = 0.0 if catalyst else 3.0
        if not catalyst:
            warnings.append("no_catalyst_flag")

        danger_score = clamp(
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
