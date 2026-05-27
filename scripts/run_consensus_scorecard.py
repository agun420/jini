"""
Consensus Scorecard
===================
Reads state/consensus_outcomes.jsonl and computes:
  - per-engine hit rate, avg max gain, avg max loss
  - per-combination hit rate (jini+engine2, jini+engine3, all three)
  - per-score-band hit rate (does final_trade_score_v3 actually predict?)
  - recommended engine weights (used by the aggregator's weighted vote)

Writes summary to state/consensus_scorecard.json.

Usage:
    PYTHONPATH=src python3 scripts/run_consensus_scorecard.py
"""

import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict
from itertools import combinations

JINI_ROOT    = Path(__file__).resolve().parent.parent
OUTCOMES_LOG = JINI_ROOT / "state" / "consensus_outcomes.jsonl"
SCORECARD    = JINI_ROOT / "state" / "consensus_scorecard.json"

MIN_SAMPLES_PER_BUCKET = 5  # below this, don't trust the hit rate


def _load_records() -> list[dict]:
    if not OUTCOMES_LOG.exists():
        return []
    return [
        json.loads(line)
        for line in OUTCOMES_LOG.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _closed_records(records: list[dict]) -> list[dict]:
    """Records with a resolved outcome."""
    return [r for r in records if r.get("outcome_hit_target") is not None]


def _bucket_stats(records: list[dict]) -> dict:
    if not records:
        return {"samples": 0, "hit_rate": None, "avg_max_gain": None, "avg_max_loss": None}
    hits = sum(1 for r in records if r.get("outcome_hit_target"))
    gains = [r.get("outcome_max_pct_gain") for r in records if r.get("outcome_max_pct_gain") is not None]
    losses = [r.get("outcome_max_pct_loss") for r in records if r.get("outcome_max_pct_loss") is not None]
    n = len(records)
    return {
        "samples":       n,
        "hit_rate":      round(hits / n, 3) if n else None,
        "avg_max_gain":  round(sum(gains) / len(gains), 3) if gains else None,
        "avg_max_loss":  round(sum(losses) / len(losses), 3) if losses else None,
    }


def _per_engine(records: list[dict]) -> dict[str, dict]:
    out: dict[str, list] = defaultdict(list)
    for r in records:
        for source in r.get("vote_sources") or []:
            out[source].append(r)
    return {name: _bucket_stats(rs) for name, rs in out.items()}


def _per_combo(records: list[dict]) -> dict[str, dict]:
    """Hit rate for every unique vote-source combination (e.g. 'jini+engine2')."""
    out: dict[str, list] = defaultdict(list)
    for r in records:
        sources = tuple(sorted(r.get("vote_sources") or []))
        if len(sources) < 2:
            continue
        # Record under exact combo AND under each pair subset for finer granularity
        out["+".join(sources)].append(r)
        if len(sources) > 2:
            for pair in combinations(sources, 2):
                out["+".join(pair) + " (any)"].append(r)
    return {combo: _bucket_stats(rs) for combo, rs in out.items()}


def _per_score_band(records: list[dict]) -> dict[str, dict]:
    bands = [(0, 65), (65, 70), (70, 75), (75, 80), (80, 100)]
    out = {}
    for lo, hi in bands:
        bucket = [r for r in records
                  if lo <= float(r.get("final_trade_score_v3") or 0) < hi]
        out[f"{lo}-{hi}"] = _bucket_stats(bucket)
    return out


def _engine_weights(per_engine: dict[str, dict]) -> dict[str, float]:
    """
    Compute weight 0.5–1.5 per engine based on hit rate.
    Engines with <MIN_SAMPLES_PER_BUCKET get neutral 1.0.
    Above 50% hit rate skews positive, below skews negative.
    """
    weights = {}
    for name, stats in per_engine.items():
        if (stats["samples"] or 0) < MIN_SAMPLES_PER_BUCKET or stats["hit_rate"] is None:
            weights[name] = 1.0
            continue
        # 0% hit → 0.5  |  50% hit → 1.0  |  100% hit → 1.5
        weights[name] = round(0.5 + stats["hit_rate"], 3)
    return weights


def main() -> None:
    records = _load_records()
    closed  = _closed_records(records)
    print(f"Loaded {len(records)} signals ({len(closed)} with resolved outcomes)")

    if not closed:
        print("No resolved outcomes yet. Run after the market closes once "
              "scripts/run_consensus_outcome_backfill.py has filled some rows.")
        return

    overall    = _bucket_stats(closed)
    per_engine = _per_engine(closed)
    per_combo  = _per_combo(closed)
    per_band   = _per_score_band(closed)
    weights    = _engine_weights(per_engine)

    payload = {
        "schema_version":  "consensus_scorecard_v1",
        "generated_at":    datetime.now(ZoneInfo("America/New_York")).isoformat(),
        "total_signals":   len(records),
        "resolved_signals": len(closed),
        "overall":         overall,
        "engines":         {name: {**stats, "weight": weights[name]}
                            for name, stats in per_engine.items()},
        "combinations":    per_combo,
        "score_bands":     per_band,
        "min_samples_per_bucket": MIN_SAMPLES_PER_BUCKET,
    }
    SCORECARD.parent.mkdir(parents=True, exist_ok=True)
    SCORECARD.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # ── Pretty print ────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"OVERALL  ({overall['samples']} signals)")
    print("=" * 60)
    print(f"  hit_rate     = {overall['hit_rate']}")
    print(f"  avg_max_gain = {overall['avg_max_gain']}%")
    print(f"  avg_max_loss = {overall['avg_max_loss']}%")

    print("\n── Per engine ─────────────────────────────────────────────")
    for name, s in sorted(per_engine.items(), key=lambda kv: -(kv[1]["hit_rate"] or 0)):
        tag = "*" if (s["samples"] or 0) < MIN_SAMPLES_PER_BUCKET else " "
        print(f"  {tag}{name:<10} n={s['samples']:3d}  hit={s['hit_rate']}  "
              f"gain={s['avg_max_gain']}%  loss={s['avg_max_loss']}%  weight={weights[name]}")
    print("  (* = sample size too small to trust)")

    print("\n── Per combination ────────────────────────────────────────")
    for combo, s in sorted(per_combo.items(), key=lambda kv: -(kv[1]["hit_rate"] or 0)):
        tag = "*" if (s["samples"] or 0) < MIN_SAMPLES_PER_BUCKET else " "
        print(f"  {tag}{combo:<30} n={s['samples']:3d}  hit={s['hit_rate']}  "
              f"gain={s['avg_max_gain']}%  loss={s['avg_max_loss']}%")

    print("\n── Per score band ─────────────────────────────────────────")
    for band, s in per_band.items():
        tag = "*" if (s["samples"] or 0) < MIN_SAMPLES_PER_BUCKET else " "
        print(f"  {tag}score {band:<10} n={s['samples']:3d}  hit={s['hit_rate']}  "
              f"gain={s['avg_max_gain']}%  loss={s['avg_max_loss']}%")

    print(f"\nWrote {SCORECARD}")


if __name__ == "__main__":
    main()
