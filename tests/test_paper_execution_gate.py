from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from prediction_engine.trade_gate.paper_execution_gate import load_guard, BASE_MAX_NOTIONAL, DEFAULT_MIN_SCORE


def test_load_guard_empty(tmp_path):
    """Test load_guard when the JSON file is empty or missing, using filesystem mocking."""
    # Create a temporary path for the test, but don't create the file
    test_path = tmp_path / "adaptive_guard.json"

    with patch("prediction_engine.trade_gate.paper_execution_gate.ADAPTIVE_GUARD_PATH", test_path):
        guard = load_guard()

        assert guard["allow_new_entries"] is True
        assert guard["risk_mode"] == "UNKNOWN"
        assert guard["min_score_required"] == DEFAULT_MIN_SCORE
        assert guard["max_notional_per_trade"] == BASE_MAX_NOTIONAL
        assert guard["reasons"] == []
        assert guard["source_loaded"] is False


def test_load_guard_valid_data(tmp_path):
    """Test load_guard with valid populated data, using filesystem mocking."""
    test_path = tmp_path / "adaptive_guard.json"
    valid_data = {
        "guard": {
            "allow_new_entries": False,
            "risk_mode": "DEFENSIVE",
            "min_score_required": 95.0,
            "max_notional_per_trade": 1500.0,
            "reasons": ["high_volatility", "recent_losses"]
        }
    }
    test_path.write_text(json.dumps(valid_data))

    with patch("prediction_engine.trade_gate.paper_execution_gate.ADAPTIVE_GUARD_PATH", test_path):
        guard = load_guard()

        assert guard["allow_new_entries"] is False
        assert guard["risk_mode"] == "DEFENSIVE"
        assert guard["min_score_required"] == 95.0
        assert guard["max_notional_per_trade"] == 1500.0
        assert guard["reasons"] == ["high_volatility", "recent_losses"]
        assert guard["source_loaded"] is True


def test_load_guard_invalid_format(tmp_path):
    """Test load_guard when 'guard' key is not a dictionary."""
    test_path = tmp_path / "adaptive_guard.json"
    invalid_data = {
        "guard": "invalid_string_instead_of_dict"
    }
    test_path.write_text(json.dumps(invalid_data))

    with patch("prediction_engine.trade_gate.paper_execution_gate.ADAPTIVE_GUARD_PATH", test_path):
        guard = load_guard()

        # Should fall back to default empty dict behavior for 'guard'
        assert guard["allow_new_entries"] is True
        assert guard["risk_mode"] == "UNKNOWN"
        assert guard["min_score_required"] == DEFAULT_MIN_SCORE
        assert guard["max_notional_per_trade"] == BASE_MAX_NOTIONAL
        assert guard["reasons"] == []
        assert guard["source_loaded"] is True


def test_load_guard_invalid_types_inside_guard(tmp_path):
    """Test load_guard when data inside the 'guard' dict has incorrect types."""
    test_path = tmp_path / "adaptive_guard.json"
    invalid_types_data = {
        "guard": {
            "allow_new_entries": "not_a_bool",
            "risk_mode": 123,
            "min_score_required": "ninety",
            "max_notional_per_trade": "a_lot",
            "reasons": "not_a_list"
        }
    }
    test_path.write_text(json.dumps(invalid_types_data))

    with patch("prediction_engine.trade_gate.paper_execution_gate.ADAPTIVE_GUARD_PATH", test_path):
        guard = load_guard()

        # bool("not_a_bool") is True
        assert guard["allow_new_entries"] is True
        assert guard["risk_mode"] == 123

        # safe_float should return None, which causes "or DEFAULT" fallback
        assert guard["min_score_required"] == DEFAULT_MIN_SCORE
        assert guard["max_notional_per_trade"] == BASE_MAX_NOTIONAL

        # reasons not a list should fall back to empty list
        assert guard["reasons"] == []
        assert guard["source_loaded"] is True
