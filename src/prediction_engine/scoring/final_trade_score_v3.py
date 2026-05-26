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


class FinalTradeScoreScorerV3:
    """
    Research-only final score.

    Combines:
    - runner potential
    - entry quality
    - opportunity quality
    - danger score

    Does not submit orders.
    Does not enable paper trading.
    Does not enable live trading.
    """

    def score_row(self, row: dict[str, Any]) -> dict[str, Any]:
        ticker = str(row.get("ticker") or row.get("symbol") or "").upper().strip()

        runner = safe_float(row.get("runner_potential_v3"))
        entry = safe_float(row.get("entry_quality_v3"))
        danger = safe_float(row.get("danger_score_v3"))

        opportunity = safe_float(row.get("opportunity_score"))
        if opportunity <= 0:
            # Fallback opportunity quality from day move + relative volume + liquidity.
            day_move = safe_float(row.get("day_move_pct"))
            rvol = safe_float(row.get("relative_volume"), 1.0)
            dollar_volume = safe_float(row.get("dollar_volume"))
            move_score = min(max(day_move, 0), 30) / 30 * 40
            rvol_score = min(max(rvol, 0), 5) / 5 * 35
            liquidity_score = min(max(dollar_volume, 0), 25_000_000) / 25_000_000 * 25
            opportunity = move_score + rvol_score + liquidity_score

        blockers: list[str] = []
        warnings: list[str] = []

        if not ticker:
            blockers.append("missing_ticker")

        if runner <= 0:
            warnings.append("runner_potential_missing_or_zero")

        if entry <= 0:
            warnings.append("entry_quality_missing_or_zero")

        if danger <= 0:
            warnings.append("danger_score_missing_or_zero")

        runner_status = str(row.get("runner_potential_status_v3") or "")
        entry_status = str(row.get("entry_quality_status_v3") or "")
        danger_status = str(row.get("danger_status_v3") or "")

        if runner_status == "RUNNER_BLOCKED":
            blockers.append("runner_blocked")

        if entry_status == "ENTRY_BLOCKED":
            blockers.append("entry_blocked")

        if danger_status == "DANGER_BLOCKED":
            blockers.append("danger_blocked")

        raw_score = (
            runner * 0.38
            + entry * 0.38
            + opportunity * 0.04
            - danger * 0.20
        )

        final_score = clamp(raw_score)

        # Conservative readiness status. This is not trade execution.
        if blockers:
            status = "FINAL_BLOCKED"
        elif final_score >= 82 and runner >= 80 and entry >= 78 and danger <= 25:
            status = "BUY_ALERT_READY_STRONG"
        elif final_score >= 70 and runner >= 65 and entry >= 62 and danger <= 45:
            status = "BUY_ALERT_WATCH"
        elif final_score >= 55:
            status = "TRACK_ONLY"
        else:
            status = "NO_EDGE"

        return {
            **row,
            "final_trade_score_v3": round(final_score, 4),
            "final_trade_score_status_v3": status,
            "final_trade_score_components_v3": {
                "runner_potential_v3": round(runner, 4),
                "entry_quality_v3": round(entry, 4),
                "opportunity_score": round(opportunity, 4),
                "danger_score_v3": round(danger, 4),
                "runner_weight": 0.40,
                "entry_weight": 0.40,
                "opportunity_weight": 0.10,
                "danger_weight": -0.10,
            },
            "final_trade_score_blockers_v3": blockers,
            "final_trade_score_warnings_v3": warnings,
            "buy_order_alert_candidate_v3": status in {"BUY_ALERT_READY_STRONG", "BUY_ALERT_WATCH"},
            "trade_eligible": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
            "order_submission": False,
            "live_trading": False,
        }

    def score(self, rows: list[dict[str, Any]], limit: int = 250) -> list[dict[str, Any]]:
        out = [self.score_row(row) for row in rows if isinstance(row, dict)]
        out.sort(key=lambda r: safe_float(r.get("final_trade_score_v3")), reverse=True)
        return out[:limit]
