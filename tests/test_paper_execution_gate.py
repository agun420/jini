import pytest
from src.prediction_engine.trade_gate.paper_execution_gate import safe_symbol

def test_safe_symbol_empty_dict():
    assert safe_symbol({}) == ""

def test_safe_symbol_only_ticker():
    assert safe_symbol({"ticker": "aapl"}) == "AAPL"

def test_safe_symbol_only_symbol():
    assert safe_symbol({"symbol": "msft"}) == "MSFT"

def test_safe_symbol_ticker_and_symbol_priority():
    assert safe_symbol({"ticker": "tsla", "symbol": "goog"}) == "TSLA"

def test_safe_symbol_whitespace_and_uppercase():
    assert safe_symbol({"ticker": "  amzn  "}) == "AMZN"
    assert safe_symbol({"symbol": "  nflx \n"}) == "NFLX"

def test_safe_symbol_none_or_empty():
    assert safe_symbol({"ticker": None}) == ""
    assert safe_symbol({"symbol": None}) == ""
    assert safe_symbol({"ticker": ""}) == ""

def test_safe_symbol_fallback_if_ticker_is_empty_or_none():
    assert safe_symbol({"ticker": None, "symbol": "meta"}) == "META"
    assert safe_symbol({"ticker": "", "symbol": "meta"}) == "META"
