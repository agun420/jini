from __future__ import annotations

from typing import Any

from prediction_engine.utils import clamp, safe_float


class RunnerPotentialScorerV3:
    """
    Research-only runner potential scorer.

    Answers: Can this stock keep running?

    Does not submit orders.
    Does not enable paper trading.
    Does not enable live trading.
    """

    # ── Component scorers ────────────────────────────────────────────────

    def _rvol_score(self, rvol: float) -> float:
        # Explosives: RVOL 5.19x avg for target hits vs 1.95x for stops
        if rvol >= 10.0:
            return 20.0
        if rvol >= 5.0:
            return 17.0
        if rvol >= 3.0:
            return 13.0
        if rvol >= 2.0:
            return 9.0
        return clamp((rvol / 2.0) * 9.0, 0, 9)

    def _day_move_score(self, day_move: float) -> float:
        if day_move >= 12:
            return 15.0
        if day_move >= 8:
            return 13.0
        if day_move >= 5:
            return 11.0
        if day_move >= 2:
            return 8.0
        return clamp((day_move / 2.0) * 8.0, 0, 8)

    def _hod_pressure_score(self, hod_dist: float) -> float:
        if hod_dist >= -1.0:
            return 10.0
        if hod_dist >= -3.0:
            return 7.0
        if hod_dist >= -6.0:
            return 4.0
        return 1.0

    def _vwap_position_score(self, vwap_dist: float, warnings: list[str]) -> float:
        if 0 <= vwap_dist <= 0.75:
            return 10.0   # winner profile
        if 0.75 < vwap_dist <= 1.5:
            return 7.0
        if 1.5 < vwap_dist <= 3.0:
            warnings.append("vwap_extension_risk")
            return 4.0
        if vwap_dist < 0:
            warnings.append("below_vwap")
            return 2.0
        warnings.append("high_vwap_extension")
        return 1.0

    def _candle_strength_runner_score(self, candle_strength: float) -> float:
        """Strong directional candles signal runner conviction."""
        if candle_strength >= 0.7:
            return 10.0
        if candle_strength >= 0.5:
            return 6.0
        if candle_strength >= 0.3:
            return 3.0
        return 0.0

    def _volume_reexpansion_runner_score(self, volume_reexpansion: float) -> float:
        """Volume re-expansion confirms breakout continuation."""
        if volume_reexpansion >= 2.0:
            return 10.0
        if volume_reexpansion >= 1.5:
            return 7.0
        if volume_reexpansion >= 1.1:
            return 4.0
        return 0.0

    # ── Public API ───────────────────────────────────────────────────────

    def score_row(self, row: dict[str, Any]) -> dict[str, Any]:
        ticker = str(row.get("ticker") or row.get("symbol") or "").upper().strip()

        price = safe_float(row.get("price"))
        day_move = safe_float(row.get("day_move_pct"))
        rvol = safe_float(row.get("relative_volume"), 1.0)
        dollar_volume = safe_float(row.get("dollar_volume"))
        vwap_dist = safe_float(row.get("vwap_distance_pct"))
        mom1 = safe_float(row.get("momentum_1m"))
        mom3 = safe_float(row.get("momentum_3m"))
        mom5 = safe_float(row.get("momentum_5m"))
        hod_dist = safe_float(row.get("high_of_day_distance_pct"))
        catalyst = bool(row.get("catalyst_flag"))
        candle_strength = safe_float(row.get("candle_strength"))
        volume_reexpansion = safe_float(row.get("volume_reexpansion"))

        blockers: list[str] = []
        warnings: list[str] = []

        if not ticker:
            blockers.append("missing_ticker")
        if price <= 0:
            blockers.append("missing_price")
        if day_move <= 0:
            warnings.append("day_move_not_positive")
        if rvol < 1:
            warnings.append("relative_volume_below_1")

        relative_volume_score = self._rvol_score(rvol)
        day_move_score = self._day_move_score(day_move)
        catalyst_score = 15.0 if catalyst else 4.0
        liquidity_score = clamp((dollar_volume / 25_000_000.0) * 10.0, 0, 10)
        hod_pressure_score = self._hod_pressure_score(hod_dist)

        momentum_sum = mom1 + mom3 + mom5
        volume_acceleration_score = clamp((momentum_sum / 6.0) * 10.0, 0, 10)

        vwap_position_score = self._vwap_position_score(vwap_dist, warnings)

        prior_runner_behavior_score = clamp(safe_float(row.get("prior_runner_score"), 5.0), 0, 10)

        candle_strength_score = self._candle_strength_runner_score(candle_strength)
        volume_reexpansion_runner_score = self._volume_reexpansion_runner_score(volume_reexpansion)

        runner_potential_score = clamp(
            relative_volume_score
            + day_move_score
            + catalyst_score
            + liquidity_score
            + hod_pressure_score
            + volume_acceleration_score
            + vwap_position_score
            + prior_runner_behavior_score
            + candle_strength_score
            + volume_reexpansion_runner_score
        )

        if runner_potential_score >= 80 and not blockers:
            status = "RUNNER_STRONG"
        elif runner_potential_score >= 65 and not blockers:
            status = "RUNNER_WATCH"
        elif not blockers:
            status = "RUNNER_WEAK"
        else:
            status = "RUNNER_BLOCKED"

        return {
            **row,
            "runner_potential_v3": round(runner_potential_score, 4),
            "runner_potential_status_v3": status,
            "runner_potential_components_v3": {
                "relative_volume_score": round(relative_volume_score, 4),
                "day_move_score": round(day_move_score, 4),
                "catalyst_score": round(catalyst_score, 4),
                "liquidity_score": round(liquidity_score, 4),
                "hod_pressure_score": round(hod_pressure_score, 4),
                "volume_acceleration_score": round(volume_acceleration_score, 4),
                "vwap_position_score": round(vwap_position_score, 4),
                "prior_runner_behavior_score": round(prior_runner_behavior_score, 4),
                "candle_strength_runner_score": round(candle_strength_score, 4),
                "volume_reexpansion_runner_score": round(volume_reexpansion_runner_score, 4),
            },
            "runner_potential_blockers_v3": blockers,
            "runner_potential_warnings_v3": warnings,
            "order_submission": False,
            "live_trading": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
        }

    def score(self, rows: list[dict[str, Any]], limit: int = 250) -> list[dict[str, Any]]:
        out = [self.score_row(row) for row in rows if isinstance(row, dict)]
        out.sort(key=lambda r: safe_float(r.get("runner_potential_v3")), reverse=True)
        return out[:limit]
