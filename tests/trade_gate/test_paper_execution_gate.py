from typing import Any, Dict
import pytest

from prediction_engine.trade_gate.paper_execution_gate import create_order_plan, BASE_MAX_NOTIONAL


def test_create_order_plan_no_signal():
    guard = {"max_notional_per_trade": 1000.0}
    account_snapshot = {"available": True, "buying_power": 10000.0}
    result = create_order_plan(None, guard, account_snapshot)

    assert result["created"] is False
    assert result["reason"] == "no_candidate"
    assert result["order"] is None


def test_create_order_plan_blocked_by_gate():
    guard = {"max_notional_per_trade": 1000.0, "min_score_required": 85.0}
    account_snapshot = {"available": True, "buying_power": 10000.0}

    # Missing ticker, entry, etc. should cause validation to fail.
    signal = {
        "ticker": "",
        "status": "NOT_ELIGIBLE",
    }

    result = create_order_plan(signal, guard, account_snapshot)

    assert result["created"] is False
    assert result["reason"] == "blocked_by_gate"
    assert "blocks" in result
    assert result["order"] is None


def test_create_order_plan_quantity_below_1():
    guard = {"max_notional_per_trade": 500.0, "min_score_required": 85.0, "allow_new_entries": True}
    account_snapshot = {"available": True, "buying_power": 10000.0, "open_position_count": 0, "open_order_count": 0}

    # Very high entry price such that floor(500 / 1000) = 0
    signal = {
        "ticker": "BRK.A",
        "status": "TRADE_ELIGIBLE",
        "score": 90.0,
        "price": 1000.0,
        "entry": 1000.0,
        "stop": 900.0,
        "target": 1200.0,
        "risk_reward": 2.0,
    }

    result = create_order_plan(signal, guard, account_snapshot)

    assert result["created"] is False
    assert result["reason"] == "quantity_below_1"
    assert result["order"] is None


def test_create_order_plan_success():
    guard = {"max_notional_per_trade": 1000.0, "min_score_required": 85.0, "allow_new_entries": True}
    account_snapshot = {"available": True, "buying_power": 10000.0, "open_position_count": 0, "open_order_count": 0}

    signal = {
        "ticker": "AAPL",
        "status": "TRADE_ELIGIBLE",
        "score": 90.0,
        "price": 150.0,
        "entry": 150.0,
        "stop": 140.0,
        "target": 180.0,
        "risk_reward": 3.0,
    }

    result = create_order_plan(signal, guard, account_snapshot)

    assert result["created"] is True
    assert result["reason"] == "paper_order_plan_created_submission_disabled_by_default"
    assert result["order"] is not None

    order = result["order"]
    assert order["symbol"] == "AAPL"

    # qty = math.floor(1000 / 150) = math.floor(6.666...) = 6
    assert order["qty"] == 6
    assert order["side"] == "buy"
    assert order["type"] == "market"
    assert order["time_in_force"] == "day"
    assert order["order_class"] == "bracket"
    assert order["take_profit"]["limit_price"] == 180.0
    assert order["stop_loss"]["stop_price"] == 140.0
    assert order["estimated_entry"] == 150.0
    assert order["estimated_notional"] == 900.0
    assert order["paper_only"] is True


def test_create_order_plan_max_notional_fallback():
    guard = {"max_notional_per_trade": 50000.0, "min_score_required": 85.0, "allow_new_entries": True}
    account_snapshot = {"available": True, "buying_power": 100000.0, "open_position_count": 0, "open_order_count": 0}

    # If max_notional_per_trade > BASE_MAX_NOTIONAL, it should fallback to BASE_MAX_NOTIONAL
    signal = {
        "ticker": "MSFT",
        "status": "TRADE_ELIGIBLE",
        "score": 90.0,
        "price": 200.0,
        "entry": 200.0,
        "stop": 180.0,
        "target": 260.0,
        "risk_reward": 3.0,
    }

    result = create_order_plan(signal, guard, account_snapshot)

    assert result["created"] is True
    order = result["order"]

    # Base max notional is 2000.0. qty = math.floor(2000 / 200) = 10
    assert order["qty"] == 10
    assert order["estimated_notional"] == 2000.0
