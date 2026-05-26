"""Tests for prediction_engine.utils."""
from __future__ import annotations

from prediction_engine.utils import clamp


def test_clamp_within_boundaries():
    assert clamp(50.0, 0.0, 100.0) == 50.0

def test_clamp_below_lower_boundary():
    assert clamp(-10.0, 0.0, 100.0) == 0.0

def test_clamp_above_upper_boundary():
    assert clamp(110.0, 0.0, 100.0) == 100.0

def test_clamp_exactly_on_lower_boundary():
    assert clamp(0.0, 0.0, 100.0) == 0.0

def test_clamp_exactly_on_upper_boundary():
    assert clamp(100.0, 0.0, 100.0) == 100.0

def test_clamp_custom_boundaries():
    assert clamp(5.0, 10.0, 20.0) == 10.0
    assert clamp(25.0, 10.0, 20.0) == 20.0
    assert clamp(15.0, 10.0, 20.0) == 15.0

def test_clamp_default_boundaries():
    # Should be 0.0 to 100.0 by default
    assert clamp(50.0) == 50.0
    assert clamp(-10.0) == 0.0
    assert clamp(110.0) == 100.0
