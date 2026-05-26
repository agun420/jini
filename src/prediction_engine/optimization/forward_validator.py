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

            if vwap_dist <= vwap_dist_max and score >= min_score:
                raw = safe_float(raw_pnl)
                atr = max(abs(safe_float(event.get("atr_at_entry"), 0.01)), 0.01)
                shares = max(safe_int(event.get("shares"), 1), 1)
                risk_unit = max(atr * shares, 1.0)
                norm_pnl = raw / risk_unit

                normalized_pnl_stream.append(norm_pnl)
                raw_pnl_stream.append(raw)

                if norm_pnl > 0:
                    wins.append(norm_pnl)
                else:
                    losses.append(norm_pnl)

        if not normalized_pnl_stream:
            return 0.0, 0.0, 0.0, 0

        equity = [0.0]
        running = 0.0
        for pnl in raw_pnl_stream:
            running += pnl
            equity.append(running)

        peak = equity[0]
        drawdowns = []

        for value in equity:
            peak = max(peak, value)
            drawdowns.append(value - peak)

        max_drawdown_dollars = min(drawdowns) if drawdowns else 0.0
        net_normalized_pnl = sum(normalized_pnl_stream)

        total_trades = len(normalized_pnl_stream)
        win_rate = len(wins) / total_trades if total_trades else 0.0
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 1.0
        expectancy_ratio = (win_rate * avg_win) / avg_loss if avg_loss > 0 else 0.0

        return net_normalized_pnl, max_drawdown_dollars, expectancy_ratio, total_trades


    def _split_and_validate_datasets(
        self,
        unified_journal_payload: list[dict[str, Any]],
        embargo_seconds: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
        trade_payload = [
            event for event in unified_journal_payload
            if event.get("record_type", "TRADE") == "TRADE"
            and event.get("outcome_pnl") is not None
            and event.get("status") == "CLOSED"
        ]

        if len(trade_payload) < 30:
            return [], [], {
                "status": "REJECTED",
                "reason": "need_30_plus_closed_trade_events",
                "closed_trade_count": len(trade_payload),
                "suggested_config_exported": False,
                "order_submission": False,
                "live_trading": False,
            }

        trade_payload.sort(key=lambda x: safe_int(x.get("entry_time")))

        split_idx = int(len(trade_payload) * 0.70)
        if split_idx <= 0 or split_idx >= len(trade_payload):
            return [], [], {
                "status": "REJECTED",
                "reason": "invalid_walk_forward_split",
                "closed_trade_count": len(trade_payload),
                "suggested_config_exported": False,
                "order_submission": False,
                "live_trading": False,
            }

        boundary_time = safe_int(trade_payload[split_idx].get("entry_time"))

        in_sample_training = [
            e for e in trade_payload[:split_idx]
            if safe_int(e.get("exit_time") or e.get("entry_time")) < boundary_time
        ]

        out_of_sample_validation = [
            e for e in trade_payload[split_idx:]
            if safe_int(e.get("entry_time")) - boundary_time > embargo_seconds
        ]

        if not self._passes_day_diversity_guard(in_sample_training, min_days=5, max_single_day_share=0.40):
            return [], [], {
                "status": "REJECTED",
                "reason": "training_set_failed_day_diversity",
                "closed_trade_count": len(trade_payload),
                "training_count": len(in_sample_training),
                "validation_count": len(out_of_sample_validation),
                "suggested_config_exported": False,
                "order_submission": False,
                "live_trading": False,
            }

        if not self._passes_day_diversity_guard(out_of_sample_validation, min_days=3, max_single_day_share=0.40):
            return [], [], {
                "status": "REJECTED",
                "reason": "validation_set_failed_day_diversity",
                "closed_trade_count": len(trade_payload),
                "training_count": len(in_sample_training),
                "validation_count": len(out_of_sample_validation),
                "suggested_config_exported": False,
                "order_submission": False,
                "live_trading": False,
            }

        return in_sample_training, out_of_sample_validation, None

    def _find_best_candidate_params(
        self,
        in_sample_training: list[dict[str, Any]],
        curr_vwap: float,
        curr_score: float,
    ) -> tuple[float, float]:
        best_in_sample_pnl = -999999.0
        candidate_vwap = curr_vwap
        candidate_score = curr_score

        for test_vwap in [0.04, 0.05, 0.06, 0.07, 0.08]:
            for test_score in [4, 5, 6, 7]:
                sim_pnl, _, _, sim_count = self._calculate_metrics(
                    in_sample_training,
                    test_vwap,
                    test_score,
                )
                if sim_count > 0 and sim_pnl > best_in_sample_pnl:
                    best_in_sample_pnl = sim_pnl
                    candidate_vwap = test_vwap
                    candidate_score = test_score

        return candidate_vwap, candidate_score

    def _build_success_response(
        self,
        guarded_vwap: float,
        guarded_score: float,
        opt_pnl: float,
        base_pnl: float,
        opt_dd: float,
        base_dd: float,
        opt_exp: float,
        base_exp: float,
        opt_count: int,
        base_count: int,
        account_dd_pct: float,
    ) -> dict[str, Any]:
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
                "normalized_r_pnl_improvement": round(opt_pnl - base_pnl, 4),
                "drawdown_variance_dollars": round(opt_dd - base_dd, 4),
                "expectancy_ratio_shift": round(opt_exp - base_exp, 4),
                "validated_drawdown_pct": round(account_dd_pct * 100, 2),
                "base_trade_count": base_count,
                "optimized_trade_count": opt_count,
            },
            "hard_safety": {
                "auto_config_overwrite": False,
                "order_submission": False,
                "live_trading": False,
            },
        }

        self.suggested_config_path.parent.mkdir(parents=True, exist_ok=True)
        self.suggested_config_path.write_text(json.dumps(suggested_payload, indent=2), encoding="utf-8")

        return {
            "status": "PASS",
            "reason": "candidate_config_cleared_validation_gates",
            "suggested_config_exported": True,
            "suggested_config_path": str(self.suggested_config_path),
            "base_metrics": {
                "pnl": round(base_pnl, 4),
                "drawdown": round(base_dd, 4),
                "expectancy": round(base_exp, 4),
                "count": base_count,
            },
            "optimized_metrics": {
                "pnl": round(opt_pnl, 4),
                "drawdown": round(opt_dd, 4),
                "expectancy": round(opt_exp, 4),
                "count": opt_count,
            },
            "order_submission": False,
            "live_trading": False,
        }

    def _build_failure_response(
        self,
        pnl_improves: bool,
        drawdown_stable: bool,
        expectancy_improves: bool,
        opt_pnl: float,
        base_pnl: float,
        opt_dd: float,
        base_dd: float,
        opt_exp: float,
        base_exp: float,
        opt_count: int,
        base_count: int,
    ) -> dict[str, Any]:
        return {
            "status": "REJECTED",
            "reason": "optimization_failed_safety_metrics",
            "pnl_improves": pnl_improves,
            "drawdown_stable": drawdown_stable,
            "expectancy_improves": expectancy_improves,
            "suggested_config_exported": False,
            "base_metrics": {
                "pnl": round(base_pnl, 4),
                "drawdown": round(base_dd, 4),
                "expectancy": round(base_exp, 4),
                "count": base_count,
            },
            "optimized_metrics": {
                "pnl": round(opt_pnl, 4),
                "drawdown": round(opt_dd, 4),
                "expectancy": round(opt_exp, 4),
                "count": opt_count,
            },
            "order_submission": False,
            "live_trading": False,
        }

    def execute_unbiased_walk_forward(
        self,
        unified_journal_payload: list[dict[str, Any]],
        embargo_seconds: int = 1800,
    ) -> dict[str, Any]:
        in_sample_training, out_of_sample_validation, error_response = self._split_and_validate_datasets(
            unified_journal_payload, embargo_seconds
        )
        if error_response:
            return error_response

        curr_vwap = safe_float(self.current_config.get("max_vwap_distance"), DEFAULT_CONFIG["max_vwap_distance"])
        curr_score = safe_float(self.current_config.get("minimum_runner_score"), DEFAULT_CONFIG["minimum_runner_score"])

        base_pnl, base_dd, base_exp, base_count = self._calculate_metrics(
            out_of_sample_validation,
            curr_vwap,
            curr_score,
        )

        candidate_vwap, candidate_score = self._find_best_candidate_params(
            in_sample_training, curr_vwap, curr_score
        )

        guarded_vwap = max(min(candidate_vwap, curr_vwap + 0.01), curr_vwap - 0.01)
        guarded_score = max(min(candidate_score, curr_score + 1), curr_score - 1)

        opt_pnl, opt_dd, opt_exp, opt_count = self._calculate_metrics(
            out_of_sample_validation,
            guarded_vwap,
            guarded_score,
        )

        account_dd_pct = opt_dd / self.starting_capital

        if account_dd_pct <= self.max_allowable_dd_pct:
            return {
                "status": "REJECTED",
                "reason": "candidate_breached_drawdown_ceiling",
                "validated_drawdown_pct": round(account_dd_pct * 100, 2),
                "suggested_config_exported": False,
                "order_submission": False,
                "live_trading": False,
            }

        pnl_improves = opt_pnl > base_pnl
        drawdown_stable = opt_dd >= base_dd
        expectancy_improves = opt_exp > base_exp

        if pnl_improves and drawdown_stable and expectancy_improves:
            return self._build_success_response(
                guarded_vwap, guarded_score,
                opt_pnl, base_pnl,
                opt_dd, base_dd,
                opt_exp, base_exp,
                opt_count, base_count,
                account_dd_pct
            )

        return self._build_failure_response(
            pnl_improves, drawdown_stable, expectancy_improves,
            opt_pnl, base_pnl,
            opt_dd, base_dd,
            opt_exp, base_exp,
            opt_count, base_count
        )
