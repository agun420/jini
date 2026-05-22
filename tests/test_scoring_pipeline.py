"""Integration tests: scoring pipeline stages chain correctly."""
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
