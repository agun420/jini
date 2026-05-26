import pytest
from src.prediction_engine.trade_gate.paper_execution_gate import validate_signal, ALLOWED_STATUS, DEFAULT_MIN_SCORE, BASE_MAX_NOTIONAL, MIN_PRICE, MAX_OPEN_POSITIONS

@pytest.fixture
def base_signal():
    return {
        "ticker": "AAPL",
        "status": ALLOWED_STATUS,
        "score": DEFAULT_MIN_SCORE + 5.0,
        "price": MIN_PRICE + 10.0,
        "entry": MIN_PRICE + 10.0,
        "stop": MIN_PRICE + 8.0,
        "target": MIN_PRICE + 15.0,
        "risk_reward": 2.5,
        "raw": {
            "quality_gate_status": "QUALITY_APPROVED",
            "advanced_quality": {},
            "market_guard": {},
            "market_circuit_proxy": {}
        }
    }

@pytest.fixture
def base_guard():
    return {
        "allow_new_entries": True,
        "min_score_required": DEFAULT_MIN_SCORE,
        "max_notional_per_trade": BASE_MAX_NOTIONAL
    }

@pytest.fixture
def base_account():
    return {
        "available": True,
        "open_position_count": 0,
        "open_order_count": 0,
        "positions": [],
        "buying_power": BASE_MAX_NOTIONAL + 1000.0,
        "reason": "loaded"
    }

def test_base_signal_valid(base_signal, base_guard, base_account):
    blocks = validate_signal(base_signal, base_guard, base_account)
    assert blocks == []

def test_missing_ticker(base_signal, base_guard, base_account):
    base_signal["ticker"] = None
    blocks = validate_signal(base_signal, base_guard, base_account)
    assert "missing_ticker" in blocks

def test_status_not_allowed(base_signal, base_guard, base_account):
    base_signal["status"] = "INVALID_STATUS"
    blocks = validate_signal(base_signal, base_guard, base_account)
    assert "status_not_allowed:INVALID_STATUS" in blocks

def test_quality_gate_blocks(base_signal, base_guard, base_account):
    base_signal["raw"]["quality_gate_status"] = "QUALITY_BLOCKED"
    blocks = validate_signal(base_signal, base_guard, base_account)
    assert "quality_gate_blocks:QUALITY_BLOCKED" in blocks

def test_advanced_quality_gate_blocked(base_signal, base_guard, base_account):
    base_signal["raw"]["advanced_quality"] = {"quality_gate_status": "QUALITY_BLOCKED"}
    blocks = validate_signal(base_signal, base_guard, base_account)
    assert "advanced_quality_gate_blocked" in blocks

def test_quality_block(base_signal, base_guard, base_account):
    base_signal["raw"]["advanced_quality"] = {"quality_gate_blocks": ["LOW_LIQUIDITY", "HIGH_SPREAD"]}
    blocks = validate_signal(base_signal, base_guard, base_account)
    assert "quality_block:LOW_LIQUIDITY" in blocks
    assert "quality_block:HIGH_SPREAD" in blocks

def test_market_guard_blocks_new_entries(base_signal, base_guard, base_account):
    base_signal["raw"]["market_guard"] = {"halt_luld_status": "BLOCK_NEW_ENTRIES"}
    blocks = validate_signal(base_signal, base_guard, base_account)
    assert "market_guard_blocks_new_entries" in blocks

def test_market_guard_block(base_signal, base_guard, base_account):
    base_signal["raw"]["market_guard"] = {"halt_luld_hard_blocks": ["HALTED", "LULD_PAUSE"]}
    blocks = validate_signal(base_signal, base_guard, base_account)
    assert "market_guard_block:HALTED" in blocks
    assert "market_guard_block:LULD_PAUSE" in blocks

def test_ticker_already_held(base_signal, base_guard, base_account):
    base_account["positions"] = [{"symbol": "AAPL"}]


    blocks = validate_signal(base_signal, base_guard, base_account)
    assert "ticker_already_held" in blocks

def test_buying_power_below_required_notional(base_signal, base_guard, base_account):
    base_account["buying_power"] = 100.0
    base_guard["max_notional_per_trade"] = 500.0
    blocks = validate_signal(base_signal, base_guard, base_account)
    assert "buying_power_below_required_notional" in blocks

def test_account_snapshot_unavailable(base_signal, base_guard, base_account):
    base_account["available"] = False
    base_account["reason"] = "api_error"
    blocks = validate_signal(base_signal, base_guard, base_account)
    assert "account_snapshot_unavailable:api_error" in blocks
