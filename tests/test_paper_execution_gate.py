from __future__ import annotations

from unittest.mock import patch, call
from prediction_engine.trade_gate.paper_execution_gate import (
    export_paper_gate,
    ORDER_PLAN_STATE_PATH,
    ORDER_PLAN_DOCS_PATH,
    ORDER_GATE_HEALTH_PATH,
    ORDER_SUBMISSION_ENABLED
)


def test_export_paper_gate_happy_path():
    dummy_payload = {
        "schema_version": "paper_execution_gate_v1",
        "generated_at": "2024-05-26T15:00:00Z",
        "status": "PASS",
        "signal_source": "test_source",
        "adaptive_guard": {
            "risk_mode": "AGGRESSIVE",
            "allow_new_entries": True,
        },
        "account_snapshot": {
            "available": 10000.0,
        },
        "selected_candidate": {
            "ticker": "AAPL",
        },
        "order_plan": {
            "created": True,
        },
        "submission": {
            "submitted": True,
        },
    }

    with patch("prediction_engine.trade_gate.paper_execution_gate.build_paper_gate_payload", return_value=dummy_payload) as mock_build, \
         patch("prediction_engine.trade_gate.paper_execution_gate.write_json") as mock_write:

        result = export_paper_gate()

        mock_build.assert_called_once()

        expected_health = {
            "schema_version": "paper_execution_gate_health_v1",
            "generated_at": "2024-05-26T15:00:00Z",
            "status": "PASS",
            "order_plan_created": True,
            "order_submission_enabled": ORDER_SUBMISSION_ENABLED,
            "order_submitted": True,
            "selected_ticker": "AAPL",
            "risk_mode": "AGGRESSIVE",
            "allow_new_entries": True,
            "account_available": 10000.0,
            "signal_source": "test_source",
            "paper_only": True,
            "notes": [
                "Package 7 creates a paper order plan only by default.",
                "Actual submission requires PAPER_ORDER_SUBMISSION_ENABLED=true and Alpaca paper keys.",
                "Live trading is not supported.",
                "Only TRADE_ELIGIBLE can pass the gate.",
            ],
        }

        assert mock_write.call_count == 3
        mock_write.assert_has_calls([
            call(ORDER_PLAN_STATE_PATH, dummy_payload),
            call(ORDER_PLAN_DOCS_PATH, dummy_payload),
            call(ORDER_GATE_HEALTH_PATH, expected_health),
        ])

        assert result == {
            "status": "PASS",
            "order_plan_created": True,
            "order_submission_enabled": ORDER_SUBMISSION_ENABLED,
            "order_submitted": True,
            "selected_ticker": "AAPL",
            "output_state": str(ORDER_PLAN_STATE_PATH),
            "output_docs": str(ORDER_PLAN_DOCS_PATH),
            "health_path": str(ORDER_GATE_HEALTH_PATH),
        }

def test_export_paper_gate_missing_optional_fields():
    dummy_payload = {
        "generated_at": "2024-05-26T15:00:00Z",
        "status": "PASS",
        "signal_source": "test_source",
        "adaptive_guard": {},
        "account_snapshot": {},
        "order_plan": {},
        "submission": {},
        # omitted selected_candidate entirely
    }

    with patch("prediction_engine.trade_gate.paper_execution_gate.build_paper_gate_payload", return_value=dummy_payload), \
         patch("prediction_engine.trade_gate.paper_execution_gate.write_json") as mock_write:

        result = export_paper_gate()

        expected_health = {
            "schema_version": "paper_execution_gate_health_v1",
            "generated_at": "2024-05-26T15:00:00Z",
            "status": "PASS",
            "order_plan_created": False,
            "order_submission_enabled": ORDER_SUBMISSION_ENABLED,
            "order_submitted": False,
            "selected_ticker": None,
            "risk_mode": None,
            "allow_new_entries": None,
            "account_available": None,
            "signal_source": "test_source",
            "paper_only": True,
            "notes": [
                "Package 7 creates a paper order plan only by default.",
                "Actual submission requires PAPER_ORDER_SUBMISSION_ENABLED=true and Alpaca paper keys.",
                "Live trading is not supported.",
                "Only TRADE_ELIGIBLE can pass the gate.",
            ],
        }

        mock_write.assert_any_call(ORDER_GATE_HEALTH_PATH, expected_health)

        assert result == {
            "status": "PASS",
            "order_plan_created": False,
            "order_submission_enabled": ORDER_SUBMISSION_ENABLED,
            "order_submitted": False,
            "selected_ticker": None,
            "output_state": str(ORDER_PLAN_STATE_PATH),
            "output_docs": str(ORDER_PLAN_DOCS_PATH),
            "health_path": str(ORDER_GATE_HEALTH_PATH),
        }
