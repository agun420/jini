from prediction_engine.execution.asymmetric_slip import AsymmetricSlippageEngine

def test_generate_fill_profile():
    engine = AsymmetricSlippageEngine(base_slippage_pct=0.005)

    # Test valid input - ENTRY_MARKET
    res1 = engine.generate_fill_profile("ENTRY_MARKET", 100.0, 0.01, 1000.0, 1000.0, 2.0)
    assert res1["order_type"] == "ENTRY_MARKET"

    # Test invalid input
    res2 = engine.generate_fill_profile("ENTRY_MARKET", -10.0, 0.01, 1000.0, 1000.0, 2.0)
    assert res2["execution_quality_pass"] == False
    assert res2["block_reason"] == "INVALID_INPUT"

    # Test LIMIT_PROFIT
    res3 = engine.generate_fill_profile("LIMIT_PROFIT", 100.0, 0.01, 1000.0, 1000.0, 2.0)
    assert res3["order_type"] == "LIMIT_PROFIT"

    # Test STOP_PANIC
    res4 = engine.generate_fill_profile("STOP_PANIC", 100.0, 0.01, 1000.0, 1000.0, 2.0)
    assert res4["order_type"] == "STOP_PANIC"

    # Test TIME_DECAY
    res5 = engine.generate_fill_profile("TIME_DECAY", 100.0, 0.01, 1000.0, 1000.0, 2.0)
    assert res5["order_type"] == "TIME_DECAY"

    # Test OTHER
    res6 = engine.generate_fill_profile("OTHER", 100.0, 0.01, 1000.0, 1000.0, 2.0)
    assert res6["order_type"] == "OTHER"
