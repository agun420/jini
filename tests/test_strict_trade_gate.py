"""Tests for StrictTradeGateV3 and GateConfig — PR #64."""
from __future__ import annotations

import pytest

from prediction_engine.trade_gate.strict_trade_gate_v3 import GateConfig, StrictTradeGateV3


def _row(**kwargs) -> dict:
    base = {
        "ticker": "AAPL",
        "price": 25.0,
        "final_trade_score_v3": 80.0,
        "runner_potential_v3": 70.0,
        "entry_quality_v3": 65.0,
        "danger_score_v3": 20.0,
        "spread_pct": 0.010,
        "quote_age_sec": 15.0,
        "vwap_distance_pct": 1.5,
        "day_move_pct": 10.0,
        "relative_volume": 2.5,
    }
    return {**base, **kwargs}


@pytest.fixture
def gate():
    return StrictTradeGateV3()


@pytest.fixture
def gate_default_config():
    return StrictTradeGateV3(config=GateConfig())


class TestSafetyFlags:
    def test_trade_eligible_always_false(self, gate):
        result = gate.evaluate_row(_row())
        assert result["trade_eligible"] is False

    def test_paper_order_allowed_always_false(self, gate):
        assert gate.evaluate_row(_row())["paper_order_allowed"] is False

    def test_live_order_allowed_always_false(self, gate):
        assert gate.evaluate_row(_row())["live_order_allowed"] is False

    def test_order_submission_always_false(self, gate):
        assert gate.evaluate_row(_row())["order_submission"] is False

    def test_live_trading_always_false(self, gate):
        assert gate.evaluate_row(_row())["live_trading"] is False


class TestGateConfigDefaults:
    def test_default_config_is_dataclass(self):
        cfg = GateConfig()
        assert cfg.min_final_score == 70.0
        assert cfg.price_min == 10.0
        assert cfg.price_max == 75.0

    def test_gate_uses_custom_config(self):
        cfg = GateConfig(price_min=5.0, price_max=200.0)
        gate = StrictTradeGateV3(config=cfg)
        result = gate.evaluate_row(_row(price=8.0))  # would be blocked by default config
        assert "outside_validated_price_regime" not in result["trade_gate_blockers_v3"]

    def test_gate_without_config_uses_defaults(self):
        gate = StrictTradeGateV3()
        assert gate.config.min_final_score == 70.0


class TestBlockerLogic:
    def test_missing_ticker_blocks(self, gate):
        result = gate.evaluate_row(_row(ticker=""))
        assert "missing_ticker" in result["trade_gate_blockers_v3"]
        assert result["trade_gate_status_v3"] == "BUY_ORDER_ALERT_BLOCKED"

    def test_price_zero_blocks(self, gate):
        result = gate.evaluate_row(_row(price=0.0))
        assert "missing_price" in result["trade_gate_blockers_v3"]

    def test_price_outside_range_blocks(self, gate):
        result = gate.evaluate_row(_row(price=5.0))
        assert "outside_validated_price_regime" in result["trade_gate_blockers_v3"]

    def test_low_final_score_blocks(self, gate):
        result = gate.evaluate_row(_row(final_trade_score_v3=50.0))
        assert "final_score_below_gate" in result["trade_gate_blockers_v3"]

    def test_low_runner_score_blocks(self, gate):
        result = gate.evaluate_row(_row(runner_potential_v3=40.0))
        assert "runner_score_below_gate" in result["trade_gate_blockers_v3"]

    def test_low_entry_score_blocks(self, gate):
        result = gate.evaluate_row(_row(entry_quality_v3=30.0))
        assert "entry_score_below_gate" in result["trade_gate_blockers_v3"]

    def test_high_danger_blocks(self, gate):
        result = gate.evaluate_row(_row(danger_score_v3=60.0))
        assert "danger_score_above_gate" in result["trade_gate_blockers_v3"]

    def test_wide_spread_blocks(self, gate):
        result = gate.evaluate_row(_row(spread_pct=0.05))
        assert "spread_too_wide" in result["trade_gate_blockers_v3"]

    def test_stale_quote_blocks(self, gate):
        result = gate.evaluate_row(_row(quote_age_sec=120.0))
        assert "quote_stale" in result["trade_gate_blockers_v3"]


class TestReadyStatus:
    def test_good_row_is_ready(self, gate):
        result = gate.evaluate_row(_row())
        assert result["trade_gate_status_v3"] in {
            "BUY_ORDER_ALERT_READY",
            "BUY_ORDER_ALERT_READY_STRONG",
        }
        assert result["buy_order_alert_eligible_v3"] is True

    def test_strong_scores_yield_ready_strong(self, gate):
        result = gate.evaluate_row(_row(
            final_trade_score_v3=85.0,
            runner_potential_v3=82.0,
            entry_quality_v3=80.0,
            danger_score_v3=15.0,
        ))
        assert result["trade_gate_status_v3"] == "BUY_ORDER_ALERT_READY_STRONG"


class TestWarnings:
    def test_missing_spread_warns_not_blocks(self, gate):
        result = gate.evaluate_row(_row(spread_pct=-1.0))
        assert "spread_missing" in result["trade_gate_warnings_v3"]
        assert "spread_too_wide" not in result["trade_gate_blockers_v3"]

    def test_below_vwap_warns(self, gate):
        result = gate.evaluate_row(_row(vwap_distance_pct=-2.0))
        assert "below_vwap" in result["trade_gate_warnings_v3"]

    def test_low_rvol_warns(self, gate):
        result = gate.evaluate_row(_row(relative_volume=0.5))
        assert "relative_volume_below_1" in result["trade_gate_warnings_v3"]


class TestSortOrder:
    def test_evaluate_sort_eligible_first(self, gate):
        rows = [
            _row(ticker="BAD", final_trade_score_v3=50.0),  # blocked
            _row(ticker="GOOD"),                             # eligible
        ]
        evaluated = gate.evaluate(rows)
        assert evaluated[0]["buy_order_alert_eligible_v3"] is True
