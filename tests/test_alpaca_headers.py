import pytest
from prediction_engine.trade_gate.paper_execution_gate import alpaca_headers, safe_symbol

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

def test_alpaca_headers_with_alpaca_prefix(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test_key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test_secret")
    # Make sure fallbacks are not set
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)

    headers = alpaca_headers()
    assert headers == {
        "APCA-API-KEY-ID": "test_key",
        "APCA-API-SECRET-KEY": "test_secret",
        "Content-Type": "application/json",
    }

def test_alpaca_headers_with_apca_prefix(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.setenv("APCA_API_KEY_ID", "test_key_apca")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "test_secret_apca")

    headers = alpaca_headers()
    assert headers == {
        "APCA-API-KEY-ID": "test_key_apca",
        "APCA-API-SECRET-KEY": "test_secret_apca",
        "Content-Type": "application/json",
    }

def test_alpaca_headers_missing_key(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test_secret")

    headers = alpaca_headers()
    assert headers is None

def test_alpaca_headers_missing_secret(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test_key")
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)

    headers = alpaca_headers()
    assert headers is None

def test_alpaca_headers_missing_both(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)

    headers = alpaca_headers()
    assert headers is None
