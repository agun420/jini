import pytest
from prediction_engine.trade_gate.paper_execution_gate import alpaca_base_url

def test_alpaca_base_url():
    """Test that alpaca_base_url returns the expected paper endpoint."""
    assert alpaca_base_url() == "https://paper-api.alpaca.markets"
