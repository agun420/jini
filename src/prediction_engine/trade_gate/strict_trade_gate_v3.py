from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from prediction_engine.utils import safe_float


@dataclass
class GateConfig:
    """Threshold configuration for StrictTradeGateV3."""

    min_final_score: float = 70.0
    min_runner_score: float = 60.0
    min_entry_score: float = 55.0
    max_danger_score: float = 50.0
    price_min: float = 10.0
    price_max: float = 75.0
    max_spread_pct: float = 0.025
    max_quote_age_sec: float = 60.0


class StrictTradeGateV3:
    """
    Research-only strict trade gate.

    This gate can mark buy-order-alert readiness.
    It cannot place orders.
    It cannot enable paper trading.
    It cannot enable live trading.
    """

    # Package 49 validated setup — do not change without new walk-forward evidence.
    _VALIDATED_SETUP = "price_10_to_75_reclaim_5bar_high_light"
    _TARGET_PCT = 0.6
    _STOP_PCT = 0.8
    _HORIZON_MINUTES = 30

    def __init__(self, config: GateConfig | None = None) -> None:
        self.config = config or GateConfig()

    def evaluate_row(self, row: dict[str, Any]) -> dict[str, Any]:
        cfg = self.config
        ticker = str(row.get("ticker") or row.get("symbol") or "").upper().strip()

        price = safe_float(row.get("price"))
        final_score = safe_float(row.get("final_trade_score_v3"))
        runner = safe_float(row.get("runner_potential_v3"))
        entry = safe_float(row.get("entry_quality_v3"))
        danger = safe_float(row.get("danger_score_v3"))
        spread = safe_float(row.get("spread_pct"), -1.0)
        quote_age = safe_float(row.get("quote_age_sec"), -1.0)
        vwap_dist = safe_float(row.get("vwap_distance_pct"))
        day_move = safe_float(row.get("day_move_pct"))
        rvol = safe_float(row.get("relative_volume"), 1.0)

        blockers: list[str] = []
        warnings: list[str] = []

        if not ticker:
            blockers.append("missing_ticker")
        if price <= 0:
            blockers.append("missing_price")
        if price < cfg.price_min or price > cfg.price_max:
            blockers.append("outside_validated_price_regime")
        if final_score < cfg.min_final_score:
            blockers.append("final_score_below_gate")
        if runner < cfg.min_runner_score:
            blockers.append("runner_score_below_gate")
        if entry < cfg.min_entry_score:
            blockers.append("entry_score_below_gate")
        if danger > cfg.max_danger_score:
            blockers.append("danger_score_above_gate")

        if spread < 0:
            warnings.append("spread_missing")
        elif spread > cfg.max_spread_pct:
            blockers.append("spread_too_wide")

        if quote_age < 0:
            warnings.append("quote_age_missing")
        elif quote_age > cfg.max_quote_age_sec:
            blockers.append("quote_stale")

        if day_move <= 0:
            warnings.append("day_move_not_positive")
        if rvol < 1.0:
            warnings.append("relative_volume_below_1")
        if vwap_dist < 0:
            warnings.append("below_vwap")

        if blockers:
            gate_status = "BUY_ORDER_ALERT_BLOCKED"
        elif final_score >= 82 and runner >= 80 and entry >= 78 and danger <= 25:
            gate_status = "BUY_ORDER_ALERT_READY_STRONG"
        else:
            gate_status = "BUY_ORDER_ALERT_READY"

        return {
            **row,
            "trade_gate_status_v3": gate_status,
            "trade_gate_blockers_v3": blockers,
            "trade_gate_warnings_v3": warnings,
            "buy_order_alert_eligible_v3": gate_status in {
                "BUY_ORDER_ALERT_READY",
                "BUY_ORDER_ALERT_READY_STRONG",
            },
            "validated_setup_v3": self._VALIDATED_SETUP,
            "validated_target_pct_v3": self._TARGET_PCT,
            "validated_stop_pct_v3": self._STOP_PCT,
            "validated_horizon_minutes_v3": self._HORIZON_MINUTES,
            "trade_eligible": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
            "order_submission": False,
            "live_trading": False,
        }

    def evaluate(self, rows: list[dict[str, Any]], limit: int = 250) -> list[dict[str, Any]]:
        out = [self.evaluate_row(row) for row in rows if isinstance(row, dict)]
        out.sort(
            key=lambda r: (
                r.get("buy_order_alert_eligible_v3") is True,
                safe_float(r.get("final_trade_score_v3")),
                safe_float(r.get("runner_potential_v3")),
                safe_float(r.get("entry_quality_v3")),
                -safe_float(r.get("danger_score_v3")),
            ),
            reverse=True,
        )
        return out[:limit]
