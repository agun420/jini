"""Tests for DangerScoreScorerV3 — PR #65."""
from __future__ import annotations

import pytest

from prediction_engine.scoring.danger_score_v3 import DangerScoreScorerV3


@pytest.fixture
def scorer():
    return DangerScoreScorerV3()


def _row(**kwargs) -> dict:
    base = {
        "ticker": "AAPL",
        "price": 20.0,
        "vwap_distance_pct": 2.0,
        "spread_pct": 0.005,
        "quote_age_sec": 5.0,
        "day_move_pct": 8.0,
        "relative_volume": 2.5,
        "momentum_1m": 0.3,
        "momentum_3m": 0.4,
        "momentum_5m": 0.2,
        "high_of_day_distance_pct": -1.0,
        "pullback_depth_pct": -0.8,
        "volume_reexpansion": 1.5,
        "candle_strength": 0.7,
        "catalyst_flag": True,
    }
    return {**base, **kwargs}


class TestSafetyFlags:
    def test_order_submission_always_false(self, scorer):
        result = scorer.score_row(_row())
        assert result["order_submission"] is False

    def test_live_trading_always_false(self, scorer):
        result = scorer.score_row(_row())
        assert result["live_trading"] is False

    def test_paper_order_allowed_always_false(self, scorer):
        result = scorer.score_row(_row())
        assert result["paper_order_allowed"] is False

    def test_live_order_allowed_always_false(self, scorer):
        result = scorer.score_row(_row())
        assert result["live_order_allowed"] is False


class TestScoreRange:
    def test_score_within_0_100(self, scorer):
        result = scorer.score_row(_row())
        assert 0 <= result["danger_score_v3"] <= 100

    def test_missing_ticker_adds_blocker(self, scorer):
        result = scorer.score_row(_row(ticker=""))
        assert "missing_ticker" in result["danger_blockers_v3"]
        assert result["danger_status_v3"] == "DANGER_BLOCKED"

    def test_missing_price_adds_blocker(self, scorer):
        result = scorer.score_row(_row(price=0.0))
        assert "missing_price" in result["danger_blockers_v3"]


class TestExtensionPenalty:
    def test_below_vwap_warns(self, scorer):
        result = scorer.score_row(_row(vwap_distance_pct=-1.0))
        assert "below_or_at_vwap" in result["danger_warnings_v3"]

    def test_very_extended_warns(self, scorer):
        result = scorer.score_row(_row(vwap_distance_pct=10.0))
        assert "very_extended_from_vwap" in result["danger_warnings_v3"]


class TestSpreadPenalty:
    def test_very_wide_spread_blocks(self, scorer):
        result = scorer.score_row(_row(spread_pct=0.05))
        assert "spread_too_wide" in result["danger_blockers_v3"]

    def test_tight_spread_no_warning(self, scorer):
        result = scorer.score_row(_row(spread_pct=0.003))
        assert "spread_too_wide" not in result["danger_blockers_v3"]
        assert "wide_spread" not in result["danger_warnings_v3"]


class TestExhaustionPenalty:
    def test_large_move_weak_momentum_warns(self, scorer):
        result = scorer.score_row(_row(day_move_pct=25.0, momentum_1m=-0.3, momentum_3m=-0.2, momentum_5m=-0.1))
        assert "large_move_with_weak_momentum" in result["danger_warnings_v3"]

    def test_no_catalyst_adds_warning(self, scorer):
        result = scorer.score_row(_row(catalyst_flag=False))
        assert "no_catalyst_flag" in result["danger_warnings_v3"]


class TestStatusThresholds:
    def test_low_danger_status(self, scorer):
        # Tight parameters → low danger
        result = scorer.score_row(_row(
            vwap_distance_pct=1.0,
            spread_pct=0.003,
            quote_age_sec=3.0,
            day_move_pct=5.0,
            relative_volume=3.0,
            momentum_1m=0.5,
            momentum_3m=0.5,
            momentum_5m=0.5,
            pullback_depth_pct=-0.5,
            volume_reexpansion=1.8,
            catalyst_flag=True,
            candle_strength=0.9,
        ))
        assert result["danger_status_v3"] in {"DANGER_LOW", "DANGER_MEDIUM"}

    def test_high_danger_from_stale_quote(self, scorer):
        result = scorer.score_row(_row(quote_age_sec=90.0))
        assert result["danger_status_v3"] in {"DANGER_HIGH", "DANGER_BLOCKED"}


class TestComponents:
    def test_components_dict_present(self, scorer):
        result = scorer.score_row(_row())
        comps = result["danger_components_v3"]
        assert "extension_penalty" in comps
        assert "spread_penalty" in comps
        assert "stale_quote_penalty" in comps
        assert "exhaustion_penalty" in comps
        assert "failed_breakout_penalty" in comps
        assert "pullback_penalty" in comps
        assert "volume_failure_penalty" in comps
        assert "no_catalyst_penalty" in comps
        assert "candle_penalty" in comps

    def test_score_method_sorts_ascending(self, scorer):
        rows = [
            _row(ticker="HIGH", spread_pct=0.04),  # high danger
            _row(ticker="LOW", spread_pct=0.003),   # low danger
        ]
        scored = scorer.score(rows)
        scores = [r["danger_score_v3"] for r in scored]
        assert scores == sorted(scores)
