from __future__ import annotations

from prediction_engine.scanners.free_scanner_normalizer import normalize_candidate
from prediction_engine.learning.adaptive_guard import classify_guard_state


def test_trade_eligible_candidate_normalizes():
    row = {
        "ticker": "TEST",
        "price": 10.0,
        "open": 9.2,
        "previous_close": 9.0,
        "relative_volume": 3.5,
        "vwap": 9.8,
        "volume_acceleration": 1.7,
        "source_type": "unit_test",
    }
    signal = normalize_candidate(row).to_dict()
    assert signal["ticker"] == "TEST"
    assert signal["score"] >= 70
    assert signal["data_quality"]["quality"] == "GOOD"


def test_placeholder_candidate_never_trade_eligible():
    row = {
        "ticker": "PLACE",
        "price": None,
        "source_type": "placeholder_universe",
        "candidate_quality": "placeholder",
    }
    signal = normalize_candidate(row).to_dict()
    assert signal["status"] == "NO_TRADE"
    assert "missing_price" in signal["no_trade_reasons"]
    assert signal["data_quality"]["quality"] == "BAD"


def test_adaptive_guard_pauses_after_five_losses():
    outcome_summary = {
        "recent_losses_5": 5,
        "recent_losses_10": 5,
        "usable_win_loss_rows": 5,
        "win_rate": 0.0,
        "average_close_return_pct": -1.0,
        "return_observation_count": 5,
    }
    signal_summary = {"trade_eligible_count": 1}
    guard = classify_guard_state(outcome_summary, signal_summary)
    assert guard["allow_new_entries"] is False
    assert guard["risk_mode"] == "PAUSED"


def test_adaptive_guard_defensive_after_three_losses():
    outcome_summary = {
        "recent_losses_5": 3,
        "recent_losses_10": 3,
        "usable_win_loss_rows": 5,
        "win_rate": 0.4,
        "average_close_return_pct": -0.2,
        "return_observation_count": 5,
    }
    signal_summary = {"trade_eligible_count": 1}
    guard = classify_guard_state(outcome_summary, signal_summary)
    assert guard["allow_new_entries"] is True
    assert guard["risk_mode"] == "DEFENSIVE"
    assert guard["min_score_required"] >= 90
