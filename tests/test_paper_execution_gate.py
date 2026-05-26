import pytest
from unittest.mock import patch
from prediction_engine.trade_gate.paper_execution_gate import build_paper_gate_payload

@patch("prediction_engine.trade_gate.paper_execution_gate.now_utc_iso")
@patch("prediction_engine.trade_gate.paper_execution_gate.submit_order_if_enabled")
@patch("prediction_engine.trade_gate.paper_execution_gate.create_order_plan")
@patch("prediction_engine.trade_gate.paper_execution_gate.choose_best_candidate")
@patch("prediction_engine.trade_gate.paper_execution_gate.fetch_paper_account_snapshot")
@patch("prediction_engine.trade_gate.paper_execution_gate.alpaca_headers")
@patch("prediction_engine.trade_gate.paper_execution_gate.load_guard")
@patch("prediction_engine.trade_gate.paper_execution_gate.load_signal_rows")
def test_build_paper_gate_payload_happy_path(
    mock_load_signal_rows,
    mock_load_guard,
    mock_alpaca_headers,
    mock_fetch_paper_account_snapshot,
    mock_choose_best_candidate,
    mock_create_order_plan,
    mock_submit_order_if_enabled,
    mock_now_utc_iso
):
    mock_load_signal_rows.return_value = ([{"ticker": "AAPL"}], "test_source")
    mock_load_guard.return_value = {"source_loaded": True, "risk_mode": "normal"}
    mock_alpaca_headers.return_value = {"APCA-API-KEY-ID": "key"}
    mock_fetch_paper_account_snapshot.return_value = {
        "positions": [{"symbol": "MSFT"}],
        "open_orders": [],
        "buying_power": "10000"
    }
    mock_choose_best_candidate.return_value = ({"ticker": "AAPL"}, ["reason"])
    mock_create_order_plan.return_value = {"created": True, "order": {"symbol": "AAPL"}}
    mock_submit_order_if_enabled.return_value = {"submitted": True, "reason": "paper_order_submitted"}
    mock_now_utc_iso.return_value = "2024-01-01T00:00:00+00:00"

    payload = build_paper_gate_payload()

    assert payload["schema_version"] == "paper_execution_gate_v1"
    assert payload["generated_at"] == "2024-01-01T00:00:00+00:00"
    assert payload["status"] == "PASS"
    assert payload["mode"] == "paper_only_order_plan"
    assert payload["signal_source"] == "test_source"
    assert payload["adaptive_guard_loaded"] is True
    assert payload["adaptive_guard"] == {"source_loaded": True, "risk_mode": "normal"}
    assert "positions" not in payload["account_snapshot"]
    assert "open_orders" not in payload["account_snapshot"]
    assert payload["account_snapshot"]["buying_power"] == "10000"
    assert payload["positions"] == [{"symbol": "MSFT"}]
    assert payload["open_orders"] == []
    assert payload["candidate_selection_reasons"] == ["reason"]
    assert payload["selected_candidate"] == {"ticker": "AAPL"}
    assert payload["order_plan"] == {"created": True, "order": {"symbol": "AAPL"}}
    assert payload["submission"] == {"submitted": True, "reason": "paper_order_submitted"}
    assert payload["safety"]["paper_only"] is True


@patch("prediction_engine.trade_gate.paper_execution_gate.now_utc_iso")
@patch("prediction_engine.trade_gate.paper_execution_gate.submit_order_if_enabled")
@patch("prediction_engine.trade_gate.paper_execution_gate.create_order_plan")
@patch("prediction_engine.trade_gate.paper_execution_gate.choose_best_candidate")
@patch("prediction_engine.trade_gate.paper_execution_gate.fetch_paper_account_snapshot")
@patch("prediction_engine.trade_gate.paper_execution_gate.alpaca_headers")
@patch("prediction_engine.trade_gate.paper_execution_gate.load_guard")
@patch("prediction_engine.trade_gate.paper_execution_gate.load_signal_rows")
def test_build_paper_gate_payload_no_candidate(
    mock_load_signal_rows,
    mock_load_guard,
    mock_alpaca_headers,
    mock_fetch_paper_account_snapshot,
    mock_choose_best_candidate,
    mock_create_order_plan,
    mock_submit_order_if_enabled,
    mock_now_utc_iso
):
    mock_load_signal_rows.return_value = ([], "test_source")
    mock_load_guard.return_value = {"source_loaded": False}
    mock_alpaca_headers.return_value = None
    mock_fetch_paper_account_snapshot.return_value = {}
    mock_choose_best_candidate.return_value = (None, ["no valid candidates"])
    mock_create_order_plan.return_value = {"created": False, "reason": "no_candidate", "order": None}
    mock_submit_order_if_enabled.return_value = {"submitted": False, "reason": "no_valid_order_plan"}
    mock_now_utc_iso.return_value = "2024-01-01T00:00:00+00:00"

    payload = build_paper_gate_payload()

    assert payload["signal_source"] == "test_source"
    assert payload["adaptive_guard_loaded"] is False
    assert payload["account_snapshot"] == {}
    assert payload["positions"] == []
    assert payload["open_orders"] == []
    assert payload["candidate_selection_reasons"] == ["no valid candidates"]
    assert payload["selected_candidate"] is None
    assert payload["order_plan"]["created"] is False
    assert payload["submission"]["submitted"] is False
