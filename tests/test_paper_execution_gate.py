from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from prediction_engine.trade_gate.paper_execution_gate import (
    export_paper_gate,
    ORDER_PLAN_STATE_PATH,
    ORDER_PLAN_DOCS_PATH,
    ORDER_GATE_HEALTH_PATH,
    ORDER_SUBMISSION_ENABLED
)


@patch("prediction_engine.trade_gate.paper_execution_gate.write_json")
@patch("prediction_engine.trade_gate.paper_execution_gate.build_paper_gate_payload")
def test_export_paper_gate_success(mock_build_payload, mock_write_json):
    """Test export_paper_gate when a payload is successfully generated with all fields."""
    mock_payload = {
        "generated_at": "2023-01-01T12:00:00Z",
        "status": "PASS",
        "order_plan": {"created": True},
        "submission": {"submitted": True},
        "selected_candidate": {"ticker": "AAPL"},
        "adaptive_guard": {
            "risk_mode": "NORMAL",
            "allow_new_entries": True
        },
        "account_snapshot": {"available": True},
        "signal_source": "test_source"
    }
    mock_build_payload.return_value = mock_payload

    result = export_paper_gate()

    # Check the return dictionary
    assert result["status"] == "PASS"
    assert result["order_plan_created"] is True
    assert result["order_submission_enabled"] == ORDER_SUBMISSION_ENABLED
    assert result["order_submitted"] is True
    assert result["selected_ticker"] == "AAPL"
    assert result["output_state"] == str(ORDER_PLAN_STATE_PATH)
    assert result["output_docs"] == str(ORDER_PLAN_DOCS_PATH)
    assert result["health_path"] == str(ORDER_GATE_HEALTH_PATH)

    # Check write_json was called correctly
    assert mock_write_json.call_count == 3

    # First call: write_json(ORDER_PLAN_STATE_PATH, payload)
    mock_write_json.assert_any_call(ORDER_PLAN_STATE_PATH, mock_payload)

    # Second call: write_json(ORDER_PLAN_DOCS_PATH, payload)
    mock_write_json.assert_any_call(ORDER_PLAN_DOCS_PATH, mock_payload)

    # Third call: write_json(ORDER_GATE_HEALTH_PATH, health)
    health_call = mock_write_json.call_args_list[2]
    health_path, health_data = health_call.args
    assert health_path == ORDER_GATE_HEALTH_PATH
    assert health_data["schema_version"] == "paper_execution_gate_health_v1"
    assert health_data["generated_at"] == "2023-01-01T12:00:00Z"
    assert health_data["status"] == "PASS"
    assert health_data["order_plan_created"] is True
    assert health_data["order_submission_enabled"] == ORDER_SUBMISSION_ENABLED
    assert health_data["order_submitted"] is True
    assert health_data["selected_ticker"] == "AAPL"
    assert health_data["risk_mode"] == "NORMAL"
    assert health_data["allow_new_entries"] is True
    assert health_data["account_available"] is True
    assert health_data["signal_source"] == "test_source"
    assert health_data["paper_only"] is True


@patch("prediction_engine.trade_gate.paper_execution_gate.write_json")
@patch("prediction_engine.trade_gate.paper_execution_gate.build_paper_gate_payload")
def test_export_paper_gate_missing_values(mock_build_payload, mock_write_json):
    """Test export_paper_gate handles missing optional fields correctly."""
    mock_payload = {
        "generated_at": "2023-01-01T12:00:00Z",
        "status": "FAIL",
        "order_plan": {},
        "submission": {},
        "adaptive_guard": {},
        "account_snapshot": {},
        "signal_source": "test_source"
        # selected_candidate missing
    }
    mock_build_payload.return_value = mock_payload

    result = export_paper_gate()

    # Check return dictionary defaults
    assert result["status"] == "PASS" # Hardcoded PASS in export_paper_gate
    assert result["order_plan_created"] is False
    assert result["order_submitted"] is False
    assert result["selected_ticker"] is None

    # Check health data defaults
    health_call = mock_write_json.call_args_list[2]
    _, health_data = health_call.args
    assert health_data["order_plan_created"] is False
    assert health_data["order_submitted"] is False
    assert health_data["selected_ticker"] is None
    assert health_data["risk_mode"] is None
    assert health_data["allow_new_entries"] is None
    assert health_data["account_available"] is None
