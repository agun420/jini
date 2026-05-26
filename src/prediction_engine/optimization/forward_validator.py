from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = {
    "max_vwap_distance": 0.06,
    "minimum_runner_score": 5,
    "max_allowed_spread": 0.015,
}

_VWAP_GRID = [0.04, 0.05, 0.06, 0.07, 0.08]
_SCORE_GRID = [4, 5, 6, 7]


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


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rejected(reason: str, **extra: Any) -> dict[str, Any]:
    return {
        "status": "REJECTED",
        "reason": reason,
        "suggested_config_exported": False,
        "order_submission": False,
        "live_trading": False,
        **extra,
    }


class ForwardValidationOptimizer:
    """
    Research-only forward validator.

    This module:
    - does not submit orders
    - does not enable paper trading
    - does not enable live trading
    - does not overwrite runtime config
    - only exports suggested_config when validation gates pass
    """

    def __init__(
        self,
        current_config_path: str | Path = "state/prediction_engine/runner_config.json",
        suggested_config_path: str | Path = "state/prediction_engine/suggested_config.json",
        starting_capital: float = 2000.0,
    ):
        self.current_config_path = Path(current_config_path)
        self.suggested_config_path = Path(suggested_config_path)
        self.starting_capital = float(starting_capital)
        self.max_allowable_dd_pct = -0.10
        self.current_config = self._load_or_create_config()

    def _load_or_create_config(self) -> dict[str, Any]:
        self.current_config_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.current_config_path.exists():
            self.current_config_path.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
            return dict(DEFAULT_CONFIG)
        try:
            data = json.loads(self.current_config_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return dict(DEFAULT_CONFIG)
            return {**DEFAULT_CONFIG, **data}
        except Exception:
            return dict(DEFAULT_CONFIG)

    def _passes_day_diversity_guard(
        self,
        dataset: list[dict[str, Any]],
        min_days: int,
        max_single_day_share: float,
    ) -> bool:
        if not dataset:
            return False
        days: dict[str, int] = {}
        for event in dataset:
            entry_time = safe_int(event.get("entry_time"))
            if entry_time <= 0:
                continue
            day = datetime.fromtimestamp(entry_time, timezone.utc).strftime("%Y-%m-%d")
            days[day] = days.get(day, 0) + 1
        if len(days) < min_days:
            return False
        max_share = max(days.values()) / max(len(dataset), 1)
        return max_share <= max_single_day_share

    def _calculate_metrics(
        self,
        dataset: list[dict[str, Any]],
        vwap_dist_max: float,
        min_score: float,
    ) -> tuple[float, float, float, int]:
        normalized_pnl_stream: list[float] = []
        raw_pnl_stream: list[float] = []
        wins: list[float] = []
        losses: list[float] = []

        for event in dataset:
            vwap_dist = abs(safe_float(event.get("vwap_dist")))
            score = safe_float(event.get("score"))
            raw_pnl = event.get("outcome_pnl")
            if raw_pnl is None:
                continue
            if vwap_dist > vwap_dist_max or score < min_score:
                continue

            raw = safe_float(raw_pnl)
            atr = max(abs(safe_float(event.get("atr_at_entry"), 0.01)), 0.01)
            shares = max(safe_int(event.get("shares"), 1), 1)
            norm_pnl = raw / max(atr * shares, 1.0)

            normalized_pnl_stream.append(norm_pnl)
            raw_pnl_stream.append(raw)
            (wins if norm_pnl > 0 else losses).append(norm_pnl)

        if not normalized_pnl_stream:
            return 0.0, 0.0, 0.0, 0

        peak = 0.0
        running = 0.0
        min_drawdown = 0.0
        for pnl in raw_pnl_stream:
            running += pnl
            peak = max(peak, running)
            min_drawdown = min(min_drawdown, running - peak)

        total = len(normalized_pnl_stream)
        win_rate = len(wins) / total
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 1.0
        expectancy_ratio = (win_rate * avg_win) / avg_loss if avg_loss > 0 else 0.0

        return sum(normalized_pnl_stream), min_drawdown, expectancy_ratio, total

    def _split_dataset(
        self, trade_payload: list[dict[str, Any]], embargo_seconds: int
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
        """Split sorted trades into in-sample / OOS with embargo gap."""
        split_idx = int(len(trade_payload) * 0.70)
        boundary_time = safe_int(trade_payload[split_idx].get("entry_time"))

        in_sample = [
            e for e in trade_payload[:split_idx]
            if safe_int(e.get("exit_time") or e.get("entry_time")) < boundary_time
        ]
        oos = [
            e for e in trade_payload[split_idx:]
            if safe_int(e.get("entry_time")) - boundary_time > embargo_seconds
        ]
        return in_sample, oos, split_idx

    def _select_candidate_config(
        self,
        in_sample: list[dict[str, Any]],
        curr_vwap: float,
        curr_score: float,
    ) -> tuple[float, float]:
        """Grid-search in-sample to find best (vwap, score) candidate."""
        best_pnl = -999999.0
        candidate_vwap = curr_vwap
        candidate_score = curr_score

        for test_vwap in _VWAP_GRID:
            for test_score in _SCORE_GRID:
                sim_pnl, _, _, sim_count = self._calculate_metrics(in_sample, test_vwap, test_score)
                if sim_count > 0 and sim_pnl > best_pnl:
                    best_pnl = sim_pnl
                    candidate_vwap = test_vwap
                    candidate_score = test_score

        return candidate_vwap, candidate_score

    def _apply_guard_rails(
        self, candidate_vwap: float, candidate_score: float, curr_vwap: float, curr_score: float
    ) -> tuple[float, float]:
        """Clamp candidate config to ±1 step from current to prevent large jumps."""
        guarded_vwap = max(min(candidate_vwap, curr_vwap + 0.01), curr_vwap - 0.01)
        guarded_score = max(min(candidate_score, curr_score + 1), curr_score - 1)
        return guarded_vwap, guarded_score

    def _export_suggested_config(
        self, guarded_vwap: float, guarded_score: float,
        base_metrics: dict[str, Any], opt_metrics: dict[str, Any],
    ) -> str:
        suggested_payload = {
            "schema_version": "suggested_config_v1",
            "generated_at": utc_now_iso(),
            "status": "SUGGESTED_ONLY",
            "max_vwap_distance": round(guarded_vwap, 3),
            "minimum_runner_score": int(guarded_score),
            "max_allowed_spread": safe_float(
                self.current_config.get("max_allowed_spread"),
                DEFAULT_CONFIG["max_allowed_spread"],
            ),
            "metrics_delta": {
                "normalized_r_pnl_improvement": round(opt_metrics["pnl"] - base_metrics["pnl"], 4),
                "drawdown_variance_dollars": round(opt_metrics["drawdown"] - base_metrics["drawdown"], 4),
                "expectancy_ratio_shift": round(opt_metrics["expectancy"] - base_metrics["expectancy"], 4),
                "validated_drawdown_pct": round(opt_metrics["dd_pct"] * 100, 2),
                "base_trade_count": base_metrics["count"],
                "optimized_trade_count": opt_metrics["count"],
            },
            "hard_safety": {
                "auto_config_overwrite": False,
                "order_submission": False,
                "live_trading": False,
            },
        }
        self.suggested_config_path.parent.mkdir(parents=True, exist_ok=True)
        self.suggested_config_path.write_text(json.dumps(suggested_payload, indent=2), encoding="utf-8")
        return str(self.suggested_config_path)

    def execute_unbiased_walk_forward(
        self,
        unified_journal_payload: list[dict[str, Any]],
        embargo_seconds: int = 1800,
    ) -> dict[str, Any]:
        trade_payload = [
            e for e in unified_journal_payload
            if e.get("record_type", "TRADE") == "TRADE"
            and e.get("outcome_pnl") is not None
            and e.get("status") == "CLOSED"
        ]

        if len(trade_payload) < 30:
            return _rejected("need_30_plus_closed_trade_events", closed_trade_count=len(trade_payload))

        trade_payload.sort(key=lambda x: safe_int(x.get("entry_time")))

        split_idx = int(len(trade_payload) * 0.70)
        if split_idx <= 0 or split_idx >= len(trade_payload):
            return _rejected("invalid_walk_forward_split", closed_trade_count=len(trade_payload))

        in_sample, oos, _ = self._split_dataset(trade_payload, embargo_seconds)

        if not self._passes_day_diversity_guard(in_sample, min_days=5, max_single_day_share=0.40):
            return _rejected(
                "training_set_failed_day_diversity",
                closed_trade_count=len(trade_payload),
                training_count=len(in_sample),
                validation_count=len(oos),
            )

        if not self._passes_day_diversity_guard(oos, min_days=3, max_single_day_share=0.40):
            return _rejected(
                "validation_set_failed_day_diversity",
                closed_trade_count=len(trade_payload),
                training_count=len(in_sample),
                validation_count=len(oos),
            )

        curr_vwap = safe_float(self.current_config.get("max_vwap_distance"), DEFAULT_CONFIG["max_vwap_distance"])
        curr_score = safe_float(self.current_config.get("minimum_runner_score"), DEFAULT_CONFIG["minimum_runner_score"])

        base_pnl, base_dd, base_exp, base_count = self._calculate_metrics(oos, curr_vwap, curr_score)

        candidate_vwap, candidate_score = self._select_candidate_config(in_sample, curr_vwap, curr_score)
        guarded_vwap, guarded_score = self._apply_guard_rails(candidate_vwap, candidate_score, curr_vwap, curr_score)

        opt_pnl, opt_dd, opt_exp, opt_count = self._calculate_metrics(oos, guarded_vwap, guarded_score)
        account_dd_pct = opt_dd / self.starting_capital

        if account_dd_pct <= self.max_allowable_dd_pct:
            return _rejected(
                "candidate_breached_drawdown_ceiling",
                validated_drawdown_pct=round(account_dd_pct * 100, 2),
            )

        base_metrics = {"pnl": round(base_pnl, 4), "drawdown": round(base_dd, 4), "expectancy": round(base_exp, 4), "count": base_count}
        opt_metrics = {"pnl": round(opt_pnl, 4), "drawdown": round(opt_dd, 4), "expectancy": round(opt_exp, 4), "count": opt_count, "dd_pct": account_dd_pct}

        pnl_improves = opt_pnl > base_pnl
        drawdown_stable = opt_dd >= base_dd
        expectancy_improves = opt_exp > base_exp

        if pnl_improves and drawdown_stable and expectancy_improves:
            path = self._export_suggested_config(guarded_vwap, guarded_score, base_metrics, opt_metrics)
            return {
                "status": "PASS",
                "reason": "candidate_config_cleared_validation_gates",
                "suggested_config_exported": True,
                "suggested_config_path": path,
                "base_metrics": base_metrics,
                "optimized_metrics": opt_metrics,
                "order_submission": False,
                "live_trading": False,
            }

        return {
            **_rejected("optimization_failed_safety_metrics"),
            "pnl_improves": pnl_improves,
            "drawdown_stable": drawdown_stable,
            "expectancy_improves": expectancy_improves,
            "base_metrics": base_metrics,
            "optimized_metrics": opt_metrics,
        }
