from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = {
    "min_final_score": 70.0,
    "min_runner_score": 60.0,
    "max_allowed_spread": 0.015,
}

_FINAL_SCORE_GRID = [65.0, 68.0, 70.0, 72.0, 75.0]
_RUNNER_SCORE_GRID = [55.0, 58.0, 60.0, 62.0, 65.0]


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
        min_final_score: float,
        min_runner_score: float,
    ) -> tuple[float, float, float, int]:
        normalized_pnl_stream: list[float] = []
        raw_pnl_stream: list[float] = []
        wins: list[float] = []
        losses: list[float] = []

        for event in dataset:
            final_score = safe_float(
                event.get("final_trade_score_v3") or event.get("score")
            )
            runner_score = safe_float(
                event.get("runner_potential_v3") or event.get("score")
            )
            raw_pnl = event.get("outcome_pnl")
            if raw_pnl is None:
                continue
            if final_score < min_final_score or runner_score < min_runner_score:
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
        curr_final: float,
        curr_runner: float,
    ) -> tuple[float, float]:
        """Grid-search in-sample to find best (final_score, runner_score) candidate."""
        best_pnl = -999999.0
        candidate_final = curr_final
        candidate_runner = curr_runner

        for test_final in _FINAL_SCORE_GRID:
            for test_runner in _RUNNER_SCORE_GRID:
                sim_pnl, _, _, sim_count = self._calculate_metrics(in_sample, test_final, test_runner)
                if sim_count > 0 and sim_pnl > best_pnl:
                    best_pnl = sim_pnl
                    candidate_final = test_final
                    candidate_runner = test_runner

        return candidate_final, candidate_runner

    def _apply_guard_rails(
        self, candidate_final: float, candidate_runner: float, curr_final: float, curr_runner: float
    ) -> tuple[float, float]:
        """Clamp candidate config to ±2.5 pts from current to prevent large jumps."""
        guarded_final = max(min(candidate_final, curr_final + 2.5), curr_final - 2.5)
        guarded_runner = max(min(candidate_runner, curr_runner + 2.5), curr_runner - 2.5)
        return guarded_final, guarded_runner

    def _export_suggested_config(
        self, guarded_final: float, guarded_runner: float,
        base_metrics: dict[str, Any], opt_metrics: dict[str, Any],
    ) -> str:
        suggested_payload = {
            "schema_version": "suggested_config_v3",
            "generated_at": utc_now_iso(),
            "status": "SUGGESTED_ONLY",
            "min_final_score": round(guarded_final, 1),
            "min_runner_score": round(guarded_runner, 1),
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

        curr_final = safe_float(self.current_config.get("min_final_score"), DEFAULT_CONFIG["min_final_score"])
        curr_runner = safe_float(self.current_config.get("min_runner_score"), DEFAULT_CONFIG["min_runner_score"])

        base_pnl, base_dd, base_exp, base_count = self._calculate_metrics(oos, curr_final, curr_runner)

        candidate_final, candidate_runner = self._select_candidate_config(in_sample, curr_final, curr_runner)
        guarded_final, guarded_runner = self._apply_guard_rails(candidate_final, candidate_runner, curr_final, curr_runner)

        opt_pnl, opt_dd, opt_exp, opt_count = self._calculate_metrics(oos, guarded_final, guarded_runner)
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
            path = self._export_suggested_config(guarded_final, guarded_runner, base_metrics, opt_metrics)
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
