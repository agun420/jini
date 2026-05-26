"""Tests for paper_execution_gate.py — PRs #57 and #56."""
from __future__ import annotations

import pytest

from prediction_engine.trade_gate.paper_execution_gate import (
    DEFAULT_MIN_SCORE,
    MIN_PRICE,
    choose_best_candidate,
    create_order_plan,
    load_guard,
    normalize_signal,
    safe_symbol,
    validate_signal,
)


# ── safe_symbol ──────────────────────────────────────────────────────────


def test_safe_symbol_empty_dict():
    assert safe_symbol({}) == ""


def test_safe_symbol_only_ticker():
    assert safe_symbol({"ticker": "aapl"}) == "AAPL"


def test_safe_symbol_only_symbol():
    assert safe_symbol({"symbol": "msft"}) == "MSFT"


def test_safe_symbol_ticker_wins_over_symbol():
    assert safe_symbol({"ticker": "tsla", "symbol": "goog"}) == "TSLA"


def test_safe_symbol_strips_whitespace():
    assert safe_symbol({"ticker": "  amzn  "}) == "AMZN"
    assert safe_symbol({"symbol": "  nflx \n"}) == "NFLX"


def test_safe_symbol_none_falls_back_to_symbol():
    assert safe_symbol({"ticker": None, "symbol": "meta"}) == "META"
    assert safe_symbol({"ticker": "", "symbol": "meta"}) == "META"


# ── normalize_signal ─────────────────────────────────────────────────────


def _good_signal_row(score: float = 90.0) -> dict:
    return {
        "ticker": "AAPL",
        "status": "TRADE_ELIGIBLE",
        "score": score,
        "price": 20.0,
        "entry": 20.0,
        "stop": 18.0,
        "target": 24.0,
        "risk_reward": 2.5,
        "relative_volume": 3.0,
        "vwap_distance_pct": 2.0,
    }


def test_normalize_signal_extracts_fields():
    row = _good_signal_row()
    sig = normalize_signal(row)
    assert sig["ticker"] == "AAPL"
    assert sig["score"] == 90.0
    assert sig["price"] == 20.0
    assert sig["entry"] == 20.0
    assert sig["stop"] == 18.0
    assert sig["target"] == 24.0
    assert sig["risk_reward"] == 2.5


def test_normalize_signal_missing_ticker_returns_empty():
    sig = normalize_signal({})
    assert sig["ticker"] == ""


# ── validate_signal ──────────────────────────────────────────────────────


def _make_guard(**overrides) -> dict:
    return {
        "allow_new_entries": True,
        "min_score_required": DEFAULT_MIN_SCORE,
        "max_notional_per_trade": 2000.0,
        **overrides,
    }


def test_validate_signal_passes_good_row():
    sig = normalize_signal(_good_signal_row())
    blocks = validate_signal(sig, _make_guard(), account_snapshot=None, lightweight=True)
    assert blocks == []


def test_validate_signal_blocks_missing_ticker():
    row = _good_signal_row()
    row["ticker"] = ""
    sig = normalize_signal(row)
    blocks = validate_signal(sig, _make_guard(), account_snapshot=None, lightweight=True)
    assert "missing_ticker" in blocks


def test_validate_signal_blocks_wrong_status():
    row = _good_signal_row()
    row["status"] = "WAIT"
    sig = normalize_signal(row)
    blocks = validate_signal(sig, _make_guard(), account_snapshot=None, lightweight=True)
    assert any("status_not_allowed" in b for b in blocks)


def test_validate_signal_blocks_low_score():
    sig = normalize_signal(_good_signal_row(score=50.0))
    blocks = validate_signal(sig, _make_guard(), account_snapshot=None, lightweight=True)
    assert "score_below_adaptive_minimum" in blocks


def test_validate_signal_blocks_price_below_minimum():
    row = _good_signal_row()
    row["price"] = MIN_PRICE - 1.0
    row["entry"] = MIN_PRICE - 1.0
    sig = normalize_signal(row)
    blocks = validate_signal(sig, _make_guard(), account_snapshot=None, lightweight=True)
    assert "price_below_minimum_or_missing" in blocks


def test_validate_signal_blocks_stop_above_entry():
    row = _good_signal_row()
    row["stop"] = 25.0  # above entry of 20
    sig = normalize_signal(row)
    blocks = validate_signal(sig, _make_guard(), account_snapshot=None, lightweight=True)
    assert "stop_not_below_entry" in blocks


def test_validate_signal_blocks_target_below_entry():
    row = _good_signal_row()
    row["target"] = 15.0  # below entry of 20
    sig = normalize_signal(row)
    blocks = validate_signal(sig, _make_guard(), account_snapshot=None, lightweight=True)
    assert "target_not_above_entry" in blocks


def test_validate_signal_blocks_low_rr():
    row = _good_signal_row()
    row["risk_reward"] = 1.5
    sig = normalize_signal(row)
    blocks = validate_signal(sig, _make_guard(), account_snapshot=None, lightweight=True)
    assert "risk_reward_below_2" in blocks


def test_validate_signal_blocks_adaptive_guard_off():
    sig = normalize_signal(_good_signal_row())
    blocks = validate_signal(sig, _make_guard(allow_new_entries=False), account_snapshot=None, lightweight=True)
    assert "adaptive_guard_blocks_new_entries" in blocks


# ── create_order_plan ────────────────────────────────────────────────────


def test_create_order_plan_no_signal_returns_not_created():
    plan = create_order_plan(None, _make_guard(), account_snapshot={})
    assert plan["created"] is False
    assert plan["reason"] == "no_candidate"


def test_create_order_plan_blocked_signal_returns_blocked():
    row = _good_signal_row(score=50.0)  # score too low
    sig = normalize_signal(row)
    plan = create_order_plan(sig, _make_guard(), account_snapshot={"available": False, "reason": "test"})
    assert plan["created"] is False


def test_create_order_plan_builds_bracket_order():
    row = _good_signal_row()
    sig = normalize_signal(row)
    account = {
        "available": True,
        "open_position_count": 0,
        "open_order_count": 0,
        "buying_power": 5000.0,
        "positions": [],
        "open_orders": [],
    }
    plan = create_order_plan(sig, _make_guard(), account_snapshot=account)
    assert plan["created"] is True
    order = plan["order"]
    assert order["side"] == "buy"
    assert order["order_class"] == "bracket"
    assert order["paper_only"] is True
    assert order["qty"] >= 1
    assert order["take_profit"]["limit_price"] == round(sig["target"], 2)
    assert order["stop_loss"]["stop_price"] == round(sig["stop"], 2)


# ── choose_best_candidate ────────────────────────────────────────────────


def test_choose_best_candidate_no_rows_returns_none():
    best, reasons = choose_best_candidate([], _make_guard())
    assert best is None
    assert "no_signal_passed_trade_eligible_gate" in reasons


def test_choose_best_candidate_all_blocked_returns_none():
    bad_row = {**_good_signal_row(score=40.0), "status": "WAIT"}
    best, _ = choose_best_candidate([bad_row], _make_guard())
    assert best is None


def test_choose_best_candidate_picks_highest_score():
    rows = [
        _good_signal_row(score=88.0),
        {**_good_signal_row(score=92.0), "ticker": "MSFT"},
    ]
    best, _ = choose_best_candidate(rows, _make_guard())
    assert best is not None
    assert best["ticker"] == "MSFT"


def test_choose_best_candidate_returns_eligible_row():
    rows = [_good_signal_row()]
    best, _ = choose_best_candidate(rows, _make_guard())
    assert best is not None
    assert best["ticker"] == "AAPL"


# ── load_guard (PR #63) ──────────────────────────────────────────────────


def test_load_guard_returns_defaults_when_no_file(tmp_path, monkeypatch):
    """load_guard falls back to defaults when adaptive_guard.json is missing."""
    import prediction_engine.trade_gate.paper_execution_gate as gate_module
    monkeypatch.setattr(gate_module, "ADAPTIVE_GUARD_PATH", tmp_path / "missing.json")

    guard = load_guard()

    assert guard["allow_new_entries"] is True
    assert guard["risk_mode"] == "UNKNOWN"
    assert guard["min_score_required"] == DEFAULT_MIN_SCORE
    assert guard["source_loaded"] is False


def test_load_guard_reads_file_values(tmp_path, monkeypatch):
    import json
    import prediction_engine.trade_gate.paper_execution_gate as gate_module

    guard_file = tmp_path / "adaptive_guard.json"
    guard_file.write_text(json.dumps({
        "guard": {
            "allow_new_entries": False,
            "risk_mode": "DEFENSIVE",
            "min_score_required": 78.0,
            "max_notional_per_trade": 1500.0,
            "reasons": ["drawdown_triggered"],
        }
    }), encoding="utf-8")
    monkeypatch.setattr(gate_module, "ADAPTIVE_GUARD_PATH", guard_file)

    guard = load_guard()

    assert guard["allow_new_entries"] is False
    assert guard["risk_mode"] == "DEFENSIVE"
    assert guard["min_score_required"] == 78.0
    assert guard["max_notional_per_trade"] == 1500.0
    assert "drawdown_triggered" in guard["reasons"]
    assert guard["source_loaded"] is True


def test_load_guard_tolerates_malformed_json(tmp_path, monkeypatch):
    import prediction_engine.trade_gate.paper_execution_gate as gate_module

    bad_file = tmp_path / "adaptive_guard.json"
    bad_file.write_text("{not: valid json}", encoding="utf-8")
    monkeypatch.setattr(gate_module, "ADAPTIVE_GUARD_PATH", bad_file)

    guard = load_guard()
    assert guard["allow_new_entries"] is True  # falls back to defaults
