from pathlib import Path

ROOT = Path(".").resolve()

# 1. Shared utils
utils = ROOT / "src/prediction_engine/utils.py"
utils.parent.mkdir(parents=True, exist_ok=True)
utils.write_text('''"""Shared low-level utilities for the prediction engine."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


now_utc_iso = utc_now_iso


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        x = float(value)
        return default if (math.isnan(x) or math.isinf(x)) else x
    except Exception:
        return default


def safe_float_opt(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        x = float(value)
        return default if (math.isnan(x) or math.isinf(x)) else x
    except Exception:
        return default


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def safe_symbol(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "signals", "candidates", "history", "events", "items", "records", "data", "predictions"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def read_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return json.loads(raw) if raw else default
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")
''', encoding="utf-8")
print("created src/prediction_engine/utils.py")

# 2. Pytest config
Path("pytest.ini").write_text('''[pytest]
testpaths = tests
addopts = -v --tb=short
pythonpath = src .
''', encoding="utf-8")

Path("pyproject.toml").write_text('''[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "jini-prediction-engine"
version = "0.32.0"
requires-python = ">=3.9"
description = "Jini quantitative signal pipeline"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src", "."]
addopts = "-v --tb=short"
''', encoding="utf-8")

Path("requirements.txt").write_text('''# Runtime
# Core pipeline is mostly stdlib.

# Testing
pytest>=7.4
pytest-timeout>=2.1
''', encoding="utf-8")

# 3. Test fixtures
tests = Path("tests")
tests.mkdir(exist_ok=True)

(tests / "conftest.py").write_text('''"""Shared fixtures for Jini prediction engine tests."""
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
''', encoding="utf-8")

(tests / "test_scoring_pipeline.py").write_text('''"""Integration tests: scoring pipeline stages chain correctly."""
from __future__ import annotations

from prediction_engine.scoring.runner_potential_v3 import RunnerPotentialScorerV3
from prediction_engine.scoring.entry_quality_v3 import EntryQualityScorerV3
from prediction_engine.scoring.danger_score_v3 import DangerScoreScorerV3
from prediction_engine.scoring.final_trade_score_v3 import FinalTradeScoreScorerV3


def test_full_pipeline_produces_scores_and_safety_flags(minimal_row):
    row = minimal_row
    row = RunnerPotentialScorerV3().score_row(row)
    row = EntryQualityScorerV3().score_row(row)
    row = DangerScoreScorerV3().score_row(row)
    row = FinalTradeScoreScorerV3().score_row(row)

    assert "runner_potential_v3" in row
    assert "entry_quality_v3" in row
    assert "danger_score_v3" in row
    assert "final_trade_score_v3" in row
    assert row.get("order_submission") is False
    assert row.get("live_trading") is False


def test_blocked_row_creates_at_least_one_blocker(blocked_row):
    row = blocked_row
    row = RunnerPotentialScorerV3().score_row(row)
    row = EntryQualityScorerV3().score_row(row)
    row = DangerScoreScorerV3().score_row(row)
    row = FinalTradeScoreScorerV3().score_row(row)

    all_blockers = (
        row.get("runner_potential_blockers_v3", [])
        + row.get("entry_quality_blockers_v3", [])
        + row.get("danger_blockers_v3", [])
        + row.get("final_trade_score_blockers_v3", [])
    )
    assert len(all_blockers) > 0


def test_score_sort_order_descending(minimal_row):
    rows = [
        {**minimal_row, "ticker": "LOW", "day_move_pct": 1.0, "relative_volume": 0.5},
        {**minimal_row, "ticker": "HIGH", "day_move_pct": 18.0, "relative_volume": 4.5},
    ]

    scored_rows = []
    for r in rows:
        r = RunnerPotentialScorerV3().score_row(r)
        r = EntryQualityScorerV3().score_row(r)
        r = DangerScoreScorerV3().score_row(r)
        r = FinalTradeScoreScorerV3().score_row(r)
        scored_rows.append(r)

    scored = FinalTradeScoreScorerV3().score(scored_rows)
    scores = [r["final_trade_score_v3"] for r in scored]
    assert scores == sorted(scores, reverse=True)
''', encoding="utf-8")

print("created pytest config and scoring pipeline tests")
