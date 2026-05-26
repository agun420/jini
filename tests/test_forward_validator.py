"""Tests for ForwardValidationOptimizer — PR #68."""
from __future__ import annotations

import json
import time

import pytest

from prediction_engine.optimization.forward_validator import ForwardValidationOptimizer


def _make_trade(entry_time: int, exit_time: int, pnl: float, day_offset: int = 0) -> dict:
    """Helper: build a closed trade event with v3 score fields."""
    return {
        "record_type": "TRADE",
        "status": "CLOSED",
        "entry_time": entry_time,
        "exit_time": exit_time,
        "outcome_pnl": pnl,
        "final_trade_score_v3": 72.0,
        "runner_potential_v3": 68.0,
        "vwap_distance_pct": 1.5,
        "atr_at_entry": 0.5,
        "shares": 100,
    }


def _make_diverse_journal(n: int = 60) -> list[dict]:
    """Generate n trades spread across multiple weekdays at noon UTC."""
    trades = []
    base = 1_700_000_000  # arbitrary fixed timestamp
    # 5 trades per day, 12 days
    for day in range(n // 5 + 1):
        day_base = base + day * 86_400
        for i in range(5):
            if len(trades) >= n:
                break
            t = day_base + i * 600
            pnl = 50.0 if (day + i) % 3 != 0 else -30.0
            trades.append(_make_trade(t, t + 300, pnl))
    return trades[:n]


@pytest.fixture
def optimizer(tmp_path):
    return ForwardValidationOptimizer(
        current_config_path=tmp_path / "runner_config.json",
        suggested_config_path=tmp_path / "suggested_config.json",
        starting_capital=2000.0,
    )


class TestRejectionCases:
    def test_fewer_than_30_trades_rejected(self, optimizer):
        result = optimizer.execute_unbiased_walk_forward([_make_trade(1_700_000_000, 1_700_000_300, 10.0)] * 20)
        assert result["status"] == "REJECTED"
        assert result["reason"] == "need_30_plus_closed_trade_events"

    def test_non_trade_records_excluded(self, optimizer):
        non_trade = {"record_type": "SIGNAL", "status": "CLOSED", "outcome_pnl": 10.0}
        journal = [non_trade] * 50
        result = optimizer.execute_unbiased_walk_forward(journal)
        assert result["status"] == "REJECTED"
        assert "need_30_plus_closed_trade_events" in result["reason"]

    def test_open_trades_excluded(self, optimizer):
        open_trade = {**_make_trade(1_700_000_000, 1_700_000_300, 10.0), "status": "OPEN"}
        journal = [open_trade] * 50
        result = optimizer.execute_unbiased_walk_forward(journal)
        assert result["status"] == "REJECTED"

    def test_missing_pnl_excluded(self, optimizer):
        no_pnl = {"record_type": "TRADE", "status": "CLOSED", "entry_time": 1_700_000_000, "exit_time": 1_700_000_300}
        journal = [no_pnl] * 50
        result = optimizer.execute_unbiased_walk_forward(journal)
        assert result["status"] == "REJECTED"


class TestDiverseJournal:
    def test_diverse_journal_passes_or_gives_clear_reason(self, optimizer):
        journal = _make_diverse_journal(60)
        result = optimizer.execute_unbiased_walk_forward(journal)
        # Either PASS or a clear REJECTED reason — never an exception.
        assert result["status"] in {"PASS", "REJECTED"}
        assert "order_submission" in result
        assert result["order_submission"] is False

    def test_safety_flags_always_false(self, optimizer):
        journal = _make_diverse_journal(60)
        result = optimizer.execute_unbiased_walk_forward(journal)
        assert result.get("order_submission") is False
        assert result.get("live_trading") is False

    def test_pass_exports_suggested_config(self, tmp_path):
        optimizer = ForwardValidationOptimizer(
            current_config_path=tmp_path / "runner_config.json",
            suggested_config_path=tmp_path / "suggested_config.json",
        )
        journal = _make_diverse_journal(60)
        result = optimizer.execute_unbiased_walk_forward(journal)
        if result["status"] == "PASS":
            assert (tmp_path / "suggested_config.json").exists()
            payload = json.loads((tmp_path / "suggested_config.json").read_text())
            assert payload["hard_safety"]["order_submission"] is False
            assert payload["hard_safety"]["live_trading"] is False


class TestHelpers:
    def test_calculate_metrics_empty_returns_zeros(self, optimizer):
        pnl, dd, exp, count = optimizer._calculate_metrics([], 70.0, 60.0)
        assert pnl == 0.0
        assert dd == 0.0
        assert exp == 0.0
        assert count == 0

    def test_passes_day_diversity_guard_empty(self, optimizer):
        assert optimizer._passes_day_diversity_guard([], min_days=1, max_single_day_share=0.5) is False

    def test_passes_day_diversity_guard_single_day(self, optimizer):
        trades = [_make_trade(1_700_000_000 + i * 60, 1_700_000_300 + i * 60, 10.0) for i in range(10)]
        assert optimizer._passes_day_diversity_guard(trades, min_days=2, max_single_day_share=0.5) is False

    def test_apply_guard_rails_clamps(self, optimizer):
        guarded_final, guarded_runner = optimizer._apply_guard_rails(80.0, 70.0, curr_final=70.0, curr_runner=60.0)
        assert guarded_final <= 70.0 + 2.5
        assert guarded_runner <= 60.0 + 2.5
