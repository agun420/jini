"""Tests for choose_best_candidate in paper_execution_gate."""
from __future__ import annotations

from typing import Any, Dict, List

from prediction_engine.trade_gate.paper_execution_gate import choose_best_candidate


def get_base_guard() -> Dict[str, Any]:
    return {
        "min_score_required": 85.0,
        "allow_new_entries": True,
        "max_notional_per_trade": 1000.0,
    }


def get_valid_signal(ticker: str = "AAPL", score: float = 90.0, rel_vol: float = 1.0, risk_reward: float = 2.5) -> Dict[str, Any]:
    return {
        "ticker": ticker,
        "status": "TRADE_ELIGIBLE",
        "score": score,
        "price": 100.0,
        "entry": 100.0,
        "stop": 90.0,
        "target": 125.0,
        "risk_reward": risk_reward,
        "relative_volume": rel_vol,
        "quality_gate_status": "QUALITY_APPROVED",
    }


def test_choose_best_candidate_no_candidates_returns_none():
    guard = get_base_guard()

    # Empty list
    best, reasons = choose_best_candidate([], guard)
    assert best is None
    assert "no_signal_passed_trade_eligible_gate" in reasons

    # List with only invalid signals (e.g. missing ticker)
    invalid_signal = get_valid_signal()
    invalid_signal["ticker"] = ""

    best, reasons = choose_best_candidate([invalid_signal], guard)
    assert best is None
    assert "no_signal_passed_trade_eligible_gate" in reasons


def test_choose_best_candidate_filters_invalid_rows():
    guard = get_base_guard()

    valid = get_valid_signal("VALID", score=86.0)

    invalid = get_valid_signal("INVALID", score=99.0)
    invalid["status"] = "NOT_ELIGIBLE"

    invalid_score = get_valid_signal("BAD_SCORE", score=80.0)

    rows = [invalid, invalid_score, valid]
    best, reasons = choose_best_candidate(rows, guard)

    assert best is not None
    assert best["ticker"] == "VALID"
    assert not reasons


def test_choose_best_candidate_sorts_by_score():
    guard = get_base_guard()

    sig1 = get_valid_signal("SIG1", score=88.0, rel_vol=5.0)
    sig2 = get_valid_signal("SIG2", score=95.0, rel_vol=1.0)
    sig3 = get_valid_signal("SIG3", score=90.0, rel_vol=10.0)

    rows = [sig1, sig2, sig3]
    best, _ = choose_best_candidate(rows, guard)

    assert best is not None
    assert best["ticker"] == "SIG2"  # Highest score


def test_choose_best_candidate_sorts_by_relative_volume():
    guard = get_base_guard()

    # Same score, different relative volume
    sig1 = get_valid_signal("SIG1", score=90.0, rel_vol=2.0)
    sig2 = get_valid_signal("SIG2", score=90.0, rel_vol=5.0)
    sig3 = get_valid_signal("SIG3", score=90.0, rel_vol=3.0)

    rows = [sig1, sig2, sig3]
    best, _ = choose_best_candidate(rows, guard)

    assert best is not None
    assert best["ticker"] == "SIG2"  # Highest relative volume among tie


def test_choose_best_candidate_sorts_by_risk_reward():
    guard = get_base_guard()

    # Same score and relative volume, different risk reward
    sig1 = get_valid_signal("SIG1", score=90.0, rel_vol=3.0, risk_reward=2.5)
    sig2 = get_valid_signal("SIG2", score=90.0, rel_vol=3.0, risk_reward=4.0)
    sig3 = get_valid_signal("SIG3", score=90.0, rel_vol=3.0, risk_reward=3.0)

    rows = [sig1, sig2, sig3]
    best, _ = choose_best_candidate(rows, guard)

    assert best is not None
    assert best["ticker"] == "SIG2"  # Highest risk reward among tie
