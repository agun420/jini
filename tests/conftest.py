"""Shared fixtures for Jini prediction engine tests."""
from __future__ import annotations

import pytest


@pytest.fixture
def minimal_row():
    return {
        "ticker": "TEST",
        "price": 15.0,
        "day_move_pct": 12.0,
        "relative_volume": 3.0,
        "dollar_volume": 5_000_000.0,
        "vwap_distance_pct": 2.5,
        "momentum_1m": 0.4,
        "momentum_3m": 0.6,
        "momentum_5m": 0.5,
        "spread_pct": 0.8,
        "quote_age_sec": 5.0,
        "high_of_day_distance_pct": -1.5,
        "pullback_depth_pct": -0.8,
        "volume_reexpansion": 1.6,
        "candle_strength": 0.72,
        "catalyst_flag": True,
    }


@pytest.fixture
def blocked_row():
    return {
        "ticker": "BLCK",
        "price": 0.0,
        "spread_pct": 5.0,
        "quote_age_sec": 120.0,
    }
