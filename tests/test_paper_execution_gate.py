from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from prediction_engine.trade_gate.paper_execution_gate import fetch_paper_account_snapshot


def test_fetch_paper_account_snapshot_no_headers():
    result = fetch_paper_account_snapshot({})
    assert result["available"] is False
    assert result["reason"] == "missing_alpaca_keys"
    assert result["open_position_count"] is None
    assert result["open_order_count"] is None
    assert result["buying_power"] is None


@patch("prediction_engine.trade_gate.paper_execution_gate.urlopen")
def test_fetch_paper_account_snapshot_success(mock_urlopen):
    # Mocking successful responses for account, positions, and orders
    mock_account_response = MagicMock()
    mock_account_response.read.return_value = json.dumps({
        "buying_power": "10000.50",
        "cash": "5000.25",
        "equity": "15000.75",
        "status": "ACTIVE"
    }).encode("utf-8")

    mock_positions_response = MagicMock()
    mock_positions_response.read.return_value = json.dumps([
        {"symbol": "AAPL", "qty": "10", "market_value": "1500.00"},
        {"symbol": "MSFT", "qty": "5", "market_value": "1500.00"}
    ]).encode("utf-8")

    mock_orders_response = MagicMock()
    mock_orders_response.read.return_value = json.dumps([
        {"id": "order-1", "symbol": "TSLA"},
        {"id": "order-2", "symbol": "AMZN"}
    ]).encode("utf-8")

    # urlopen acts as a context manager so we need to set the __enter__ return value
    mock_account_response.__enter__.return_value = mock_account_response
    mock_positions_response.__enter__.return_value = mock_positions_response
    mock_orders_response.__enter__.return_value = mock_orders_response

    mock_urlopen.side_effect = [
        mock_account_response,
        mock_positions_response,
        mock_orders_response
    ]

    headers = {"APCA-API-KEY-ID": "key", "APCA-API-SECRET-KEY": "secret"}
    result = fetch_paper_account_snapshot(headers)

    assert result["available"] is True
    assert result["reason"] == "loaded"
    assert result["open_position_count"] == 2
    assert result["open_order_count"] == 2
    assert result["buying_power"] == 10000.50
    assert result["cash"] == 5000.25
    assert result["equity"] == 15000.75
    assert result["paper_account_status"] == "ACTIVE"
    assert len(result["positions"]) == 2
    assert result["positions"][0]["symbol"] == "AAPL"


@patch("prediction_engine.trade_gate.paper_execution_gate.urlopen")
def test_fetch_paper_account_snapshot_account_failure(mock_urlopen):
    mock_urlopen.side_effect = Exception("Connection Refused")

    headers = {"APCA-API-KEY-ID": "key", "APCA-API-SECRET-KEY": "secret"}
    result = fetch_paper_account_snapshot(headers)

    assert result["available"] is False
    assert "account_fetch_failed" in result["reason"]
    assert "Connection Refused" in result["reason"]


@patch("prediction_engine.trade_gate.paper_execution_gate.urlopen")
def test_fetch_paper_account_snapshot_positions_orders_failure(mock_urlopen):
    mock_account_response = MagicMock()
    mock_account_response.read.return_value = json.dumps({
        "buying_power": "10000.50",
        "cash": "5000.25",
        "equity": "15000.75",
        "status": "ACTIVE"
    }).encode("utf-8")
    mock_account_response.__enter__.return_value = mock_account_response

    # Raise exception for positions and orders
    mock_urlopen.side_effect = [
        mock_account_response,
        Exception("Positions API Error"),
        Exception("Orders API Error")
    ]

    headers = {"APCA-API-KEY-ID": "key", "APCA-API-SECRET-KEY": "secret"}
    result = fetch_paper_account_snapshot(headers)

    assert result["available"] is True
    assert result["reason"] == "loaded"
    # Even if positions and orders fail, it should not fail the whole fetch
    # It just returns empty lists
    assert result["open_position_count"] == 0
    assert result["open_order_count"] == 0
    assert result["buying_power"] == 10000.50
    assert result["positions"] == []
    assert result["open_orders"] == []
