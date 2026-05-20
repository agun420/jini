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


class RunnerPotentialScorerV3:
    """
    Research-only runner potential scorer.

    Answers:
    Can this stock keep running?

    Does not submit orders.
    Does not enable paper trading.
    Does not enable live trading.
    """

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

        # Components. Total max = 100.
        relative_volume_score = clamp((rvol / 5.0) * 20.0, 0, 20)
        day_move_score = clamp((day_move / 20.0) * 15.0, 0, 15)
        catalyst_score = 15.0 if catalyst else 4.0
        liquidity_score = clamp((dollar_volume / 25_000_000.0) * 10.0, 0, 10)

        # Near HOD is positive. Too far below HOD is weaker.
        if hod_dist >= -1.0:
            hod_pressure_score = 10.0
        elif hod_dist >= -3.0:
            hod_pressure_score = 7.0
        elif hod_dist >= -6.0:
            hod_pressure_score = 4.0
        else:
            hod_pressure_score = 1.0

        momentum_sum = mom1 + mom3 + mom5
        volume_acceleration_score = clamp((momentum_sum / 6.0) * 10.0, 0, 10)

        # Above VWAP is useful, but too extended can be risky.
        if 0 <= vwap_dist <= 4:
            vwap_position_score = 10.0
        elif 4 < vwap_dist <= 8:
            vwap_position_score = 6.0
            warnings.append("vwap_extension_risk")
        elif vwap_dist < 0:
            vwap_position_score = 2.0
            warnings.append("below_vwap")
        else:
            vwap_position_score = 3.0
            warnings.append("high_vwap_extension")

        prior_runner_behavior_score = safe_float(row.get("prior_runner_score"), 5.0)
        prior_runner_behavior_score = clamp(prior_runner_behavior_score, 0, 10)

        runner_potential_score = (
            relative_volume_score
            + day_move_score
            + catalyst_score
            + liquidity_score
            + hod_pressure_score
            + volume_acceleration_score
            + vwap_position_score
            + prior_runner_behavior_score
        )

        runner_potential_score = clamp(runner_potential_score)

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
