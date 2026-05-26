import pytest
from src.prediction_engine.trade_gate.paper_execution_gate import normalize_signal

def test_normalize_signal_happy_path():
    row = {
        "ticker": "AAPL",
        "status": "TRADE_ELIGIBLE",
        "score": 95.5,
        "price": 150.0,
        "entry": 151.0,
        "stop": 145.0,
        "target": 160.0,
        "risk_reward": 3.5,
        "relative_volume": 2.1,
        "vwap_distance_percent": 1.5,
        "trade_gate_summary": "Good setup",
        "no_trade_reasons": []
    }

    result = normalize_signal(row)

    assert result["ticker"] == "AAPL"
    assert result["status"] == "TRADE_ELIGIBLE"
    assert result["score"] == 95.5
    assert result["price"] == 150.0
    assert result["entry"] == 151.0
    assert result["stop"] == 145.0
    assert result["target"] == 160.0
    assert result["risk_reward"] == 3.5
    assert result["relative_volume"] == 2.1
    assert result["vwap_distance_percent"] == 1.5
    assert result["reason"] == "Good setup"
    assert result["no_trade_reasons"] == []
    assert result["raw"] == row

def test_normalize_signal_fallbacks():
    row = {
        "symbol": "msft",
        "signal": "APPROVED",
        "price": 200.0,
        # entry missing, should fall back to price
        "score": None, # should fall back to 0.0
        "vwap_distance_pct": 2.5,
        "reason": "Secondary reason"
    }

    result = normalize_signal(row)

    assert result["ticker"] == "MSFT" # upper case
    assert result["status"] == "APPROVED"
    assert result["score"] == 0.0
    assert result["price"] == 200.0
    assert result["entry"] == 200.0
    assert result["vwap_distance_percent"] == 2.5
    assert result["reason"] == "Secondary reason"
    assert result["no_trade_reasons"] == []

def test_normalize_signal_data_cleaning():
    row = {
        "ticker": " TSLA ",
        "price": "250.5",
        "entry": "251.0",
        "stop": "invalid",
        "target": "",
        "score": "80",
        "risk_reward": None
    }

    result = normalize_signal(row)

    assert result["ticker"] == "TSLA"
    assert result["price"] == 250.5
    assert result["entry"] == 251.0
    assert result["stop"] is None
    assert result["target"] is None
    assert result["score"] == 80.0
    assert result["risk_reward"] is None

def test_normalize_signal_empty_dict():
    result = normalize_signal({})

    assert result["ticker"] == ""
    assert result["status"] == "UNKNOWN"
    assert result["score"] == 0.0
    assert result["price"] is None
    assert result["entry"] is None
    assert result["stop"] is None
    assert result["target"] is None
    assert result["risk_reward"] is None
    assert result["relative_volume"] is None
    assert result["vwap_distance_percent"] is None
    assert result["reason"] == ""
    assert result["no_trade_reasons"] == []
    assert result["raw"] == {}

def test_normalize_signal_edge_cases():
    row = {
        "no_trade_reasons": "not a list",
        "trade_gate_summary": "",
        "reason": "fallback reason"
    }

    result = normalize_signal(row)

    assert result["no_trade_reasons"] == []
    assert result["reason"] == "fallback reason"
