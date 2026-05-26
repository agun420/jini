"""Tests for paper execution gate order submission."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import pytest

# We need to import the module to mock its ORDER_SUBMISSION_ENABLED constant later
from prediction_engine.trade_gate import paper_execution_gate
from prediction_engine.trade_gate.paper_execution_gate import submit_order_if_enabled


def test_submit_order_submission_disabled():
    with patch("prediction_engine.trade_gate.paper_execution_gate.ORDER_SUBMISSION_ENABLED", False):
        result = submit_order_if_enabled({"created": True, "order": {}}, {"Authorization": "Bearer token"})
        assert result["submitted"] is False
        assert result["reason"] == "PAPER_ORDER_SUBMISSION_ENABLED_is_false"
        assert result["response"] is None

def test_submit_order_missing_headers():
    with patch("prediction_engine.trade_gate.paper_execution_gate.ORDER_SUBMISSION_ENABLED", True):
        result = submit_order_if_enabled({"created": True, "order": {}}, None)
        assert result["submitted"] is False
        assert result["reason"] == "missing_alpaca_keys"
        assert result["response"] is None

        result2 = submit_order_if_enabled({"created": True, "order": {}}, {})
        assert result2["submitted"] is False
        assert result2["reason"] == "missing_alpaca_keys"
        assert result2["response"] is None

def test_submit_order_invalid_order_plan():
    with patch("prediction_engine.trade_gate.paper_execution_gate.ORDER_SUBMISSION_ENABLED", True):
        headers = {"Authorization": "Bearer token"}

        # Missing "created" flag
        result1 = submit_order_if_enabled({"order": {}}, headers)
        assert result1["submitted"] is False
        assert result1["reason"] == "no_valid_order_plan"

        # Missing "order" object
        result2 = submit_order_if_enabled({"created": True}, headers)
        assert result2["submitted"] is False
        assert result2["reason"] == "no_valid_order_plan"

        # "created" is False
        result3 = submit_order_if_enabled({"created": False, "order": {}}, headers)
        assert result3["submitted"] is False
        assert result3["reason"] == "no_valid_order_plan"

def test_submit_order_success():
    with patch("prediction_engine.trade_gate.paper_execution_gate.ORDER_SUBMISSION_ENABLED", True):
        with patch("prediction_engine.trade_gate.paper_execution_gate.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps({"id": "order123", "status": "accepted"}).encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_response

            order_plan = {"created": True, "order": {"symbol": "AAPL", "qty": 10}}
            headers = {"Authorization": "Bearer token"}

            result = submit_order_if_enabled(order_plan, headers)

            assert result["submitted"] is True
            assert result["reason"] == "paper_order_submitted"
            assert result["response"] == {"id": "order123", "status": "accepted"}
            mock_urlopen.assert_called_once()

def test_submit_order_network_failure():
    with patch("prediction_engine.trade_gate.paper_execution_gate.ORDER_SUBMISSION_ENABLED", True):
        with patch("prediction_engine.trade_gate.paper_execution_gate.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = Exception("Connection refused")

            order_plan = {"created": True, "order": {"symbol": "AAPL", "qty": 10}}
            headers = {"Authorization": "Bearer token"}

            result = submit_order_if_enabled(order_plan, headers)

            assert result["submitted"] is False
            assert "paper_order_submit_failed:Connection refused" in result["reason"]
            assert result["response"] is None
