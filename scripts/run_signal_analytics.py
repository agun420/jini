"""
Signal Analytics — the edge finder
==================================
Goes beyond hit rate. Reads state/consensus_outcomes.jsonl (after the backfill
has resolved outcomes) and answers the questions that actually drive refinement:

  1. EXPECTANCY (R)   — average reward-per-unit-risk. Hit rate is a vanity metric;
                        expectancy is what compounds. Computed conservatively
                        (stop-first assumption) and optimistically.
  2. CALIBRATION      — does predicted confidence match realized win rate? Bins
                        confidence deciles and compares predicted vs actual.
                        Tells you if the model is over/under-confident.
  3. FEATURE EDGE     — for each input feature, the mean for winners vs losers
                        and a separation score. Surfaces which inputs predict and
                        which are noise.
  4. SLICE BREAKDOWN  — expectancy + hit rate by setup, score-band, signal_state,
                        tier, vote_count, hour-of-day. Shows what to cut/keep.

Writes state/signal_analytics.json and prints a readable report with a
RECOMMENDATIONS section.

Usage:
    PYTHONPATH=src python3 scripts/run_signal_analytics.py
"""

import json
import math
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

JINI_ROOT    = Path(__file__).resolve().parent.parent
OUTCOMES_LOG = JINI_ROOT / "state" / "consensus_outcomes.jsonl"
OUT          = JINI_ROOT / "state" / "signal_analytics.json"
ET           = ZoneInfo("America/New_York")

MIN_SAMPLES = 8     # below this a slice is "low confidence"


# ── Load + resolve ─────────────────────────────────────────────────────────
def _load() -> list[dict]:
    if not OUTCOMES_LOG.exists():
        return []
    return [json.loads(l) for l in OUTCOMES_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]


def _resolved(recs: list[dict]) -> list[dict]:
    return [r for r in recs if r.get("outcome_hit_target") is not None
            and r.get("outcome_max_pct_gain") is not None]


def _realized_R(r: dict) -> tuple[float, float]:
    """
    Return (conservative_R, optimistic_R) for one resolved signal.

    risk%   = (entry - stop) / entry
    We can't see intrabar order, so:
      conservative — if the stop was touched at all (max_loss <= -risk%), assume
                     it hit FIRST → -1R. Else credit the better of T1/EOD.
      optimistic   — if the target was touched (max_gain >= t1 move%), credit +T1 R;
                     else mark-to-EOD.
    """
    entry = r.get("plan_entry") or r.get("entry_price")
    stop  = r.get("plan_stop")
    t1    = r.get("plan_target1")
    if not entry or not stop or entry <= 0 or stop >= entry:
        return 0.0, 0.0
    risk_pct = (entry - stop) / entry * 100
    if risk_pct <= 0:
        return 0.0, 0.0

    gain = float(r.get("outcome_max_pct_gain") or 0)
    loss = float(r.get("outcome_max_pct_loss") or 0)
    t1_move_pct = ((t1 - entry) / entry * 100) if t1 else risk_pct * 0.75

    # EOD mark in R
    eod = r.get("outcome_price_eod")
    eod_R = ((eod - entry) / entry * 100) / risk_pct if eod else 0.0

    stop_touched   = loss <= -risk_pct
    target_touched = gain >= t1_move_pct

    # Conservative: stop wins ties
    if stop_touched:
        cons = -1.0
    elif target_touched:
        cons = t1_move_pct / risk_pct
    else:
        cons = eod_R

    # Optimistic: target wins ties
    if target_touched:
        opt = t1_move_pct / risk_pct
    elif stop_touched:
        opt = -1.0
    else:
        opt = eod_R

    return round(cons, 3), round(opt, 3)


# ── Stats helpers ──────────────────────────────────────────────────────────
def _bucket(recs: list[dict]) -> dict:
    n = len(recs)
    if not n:
        return {"n": 0, "hit_rate": None, "exp_R_cons": None, "exp_R_opt": None,
                "avg_gain": None, "avg_loss": None}
    hits = sum(1 for r in recs if r.get("outcome_hit_target"))
    cons = [_realized_R(r)[0] for r in recs]
    opt  = [_realized_R(r)[1] for r in recs]
    gains = [r["outcome_max_pct_gain"] for r in recs if r.get("outcome_max_pct_gain") is not None]
    losses = [r["outcome_max_pct_loss"] for r in recs if r.get("outcome_max_pct_loss") is not None]
    return {
        "n": n,
        "hit_rate":   round(hits / n, 3),
        "exp_R_cons": round(statistics.mean(cons), 3),
        "exp_R_opt":  round(statistics.mean(opt), 3),
        "avg_gain":   round(statistics.mean(gains), 3) if gains else None,
        "avg_loss":   round(statistics.mean(losses), 3) if losses else None,
    }


def _by(recs: list[dict], keyfn) -> dict:
    groups = defaultdict(list)
    for r in recs:
        k = keyfn(r)
        if k is not None:
            groups[str(k)].append(r)
    return {k: _bucket(v) for k, v in sorted(groups.items())}


def _calibration(recs: list[dict]) -> list[dict]:
    """Bin by confidence into deciles; compare predicted vs actual win rate."""
    rows = [r for r in recs if r.get("confidence") is not None]
    if len(rows) < 10:
        return []
    out = []
    for lo in range(0, 100, 10):
        hi = lo + 10
        b = [r for r in rows if lo <= float(r.get("confidence") or 0) < hi]
        if not b:
            continue
        actual = sum(1 for r in b if r.get("outcome_hit_target")) / len(b)
        pred   = statistics.mean(float(r["confidence"]) for r in b) / 100
        out.append({"band": f"{lo}-{hi}", "n": len(b),
                    "predicted": round(pred, 3), "actual": round(actual, 3),
                    "gap": round(actual - pred, 3)})
    return out


def _feature_edge(recs: list[dict]) -> list[dict]:
    """Mean of each numeric feature for winners vs losers + separation score."""
    feats = ["final_trade_score_v3", "runner_potential_v3", "entry_quality_v3",
             "danger_score_v3", "confidence", "relative_volume_at_signal",
             "vwap_distance_pct_at_signal", "vote_count", "plan_rr"]
    win  = [r for r in recs if r.get("outcome_hit_target")]
    lose = [r for r in recs if r.get("outcome_hit_target") is False]
    if len(win) < 5 or len(lose) < 5:
        return []
    out = []
    for f in feats:
        wv = [float(r[f]) for r in win  if r.get(f) is not None]
        lv = [float(r[f]) for r in lose if r.get(f) is not None]
        if len(wv) < 3 or len(lv) < 3:
            continue
        mw, ml = statistics.mean(wv), statistics.mean(lv)
        sd = statistics.pstdev(wv + lv) or 1.0
        sep = (mw - ml) / sd                      # standardized mean difference
        out.append({"feature": f, "win_mean": round(mw, 3), "lose_mean": round(ml, 3),
                    "separation": round(sep, 3)})
    out.sort(key=lambda x: -abs(x["separation"]))
    return out


def _hour(r):
    try:
        return datetime.fromisoformat(r["timestamp"]).astimezone(ET).hour
    except Exception:
        return None


# ── Recommendations ────────────────────────────────────────────────────────
def _recommend(overall, by_setup, by_state, by_tier, calib, feat) -> list[str]:
    recs = []
    if overall["n"] < 30:
        recs.append(f"SAMPLE: only {overall['n']} resolved signals — treat everything below as directional, not conclusive. Re-run after ~50+.")

    # Expectancy verdict
    if overall["exp_R_cons"] is not None:
        if overall["exp_R_cons"] > 0.05:
            recs.append(f"EDGE: conservative expectancy is +{overall['exp_R_cons']}R — the system is net positive even assuming stops hit first. Keep going.")
        elif overall["exp_R_opt"] is not None and overall["exp_R_opt"] < 0:
            recs.append(f"NO EDGE: even optimistic expectancy is {overall['exp_R_opt']}R (<0). The current setups are not profitable — change setup logic, don't just retune thresholds.")
        else:
            recs.append(f"MARGINAL: expectancy is between {overall['exp_R_cons']}R (cons) and {overall['exp_R_opt']}R (opt). Edge is fragile — tighten entries/filters below.")

    # Calibration
    if calib:
        big_gap = [c for c in calib if c["n"] >= MIN_SAMPLES and abs(c["gap"]) > 0.15]
        if big_gap:
            over = [c for c in big_gap if c["gap"] < 0]
            if over:
                recs.append("CALIBRATION: model is OVER-confident in bands " +
                            ", ".join(c["band"] for c in over) +
                            " — actual win rate is well below predicted. Recalibrate confidence (shrink toward base rate) before trusting high-confidence cards.")

    # Setups to cut
    cut = [(k, b) for k, b in by_setup.items()
           if b["n"] >= MIN_SAMPLES and b["exp_R_cons"] is not None and b["exp_R_cons"] < -0.1]
    for k, b in cut:
        recs.append(f"CUT SETUP '{k}': {b['n']} trades, {b['exp_R_cons']}R conservative — losing money. Drop or fix this setup.")
    keep = [(k, b) for k, b in by_setup.items()
            if b["n"] >= MIN_SAMPLES and b["exp_R_cons"] is not None and b["exp_R_cons"] > 0.15]
    for k, b in keep:
        recs.append(f"FAVOR SETUP '{k}': {b['n']} trades, +{b['exp_R_cons']}R — your best edge. Weight it up / size larger.")

    # State: chasing
    ext = by_state.get("EXTENDED")
    if ext and ext["n"] >= MIN_SAMPLES and (ext["exp_R_cons"] or 0) < 0:
        recs.append(f"DON'T CHASE: EXTENDED-state entries are {ext['exp_R_cons']}R over {ext['n']} trades — confirm the dashboard is steering you away from these.")

    # Tier: is consensus actually better?
    c, w = by_tier.get("CONSENSUS"), by_tier.get("HIGH_CONVICTION")
    if c and w and c["n"] >= MIN_SAMPLES and w["n"] >= MIN_SAMPLES:
        if (c["exp_R_cons"] or 0) <= (w["exp_R_cons"] or 0):
            recs.append(f"TIER: CONSENSUS ({c['exp_R_cons']}R) is NOT beating single-engine HIGH_CONVICTION ({w['exp_R_cons']}R). The multi-engine vote may not be adding value yet — investigate engine overlap/quality.")
        else:
            recs.append(f"TIER: CONSENSUS ({c['exp_R_cons']}R) beats HIGH_CONVICTION ({w['exp_R_cons']}R) — the vote is working. Raise size on consensus.")

    # Best feature
    if feat:
        top = feat[0]
        if abs(top["separation"]) > 0.3:
            direction = "higher" if top["separation"] > 0 else "lower"
            recs.append(f"FEATURE: '{top['feature']}' separates winners best ({direction} = better, sep={top['separation']}). Weight it more in scoring; features near 0 separation are noise.")

    if not recs:
        recs.append("Not enough signal yet to make confident recommendations. Keep collecting outcomes.")
    return recs


def _fmt(b):
    if not b or b["n"] == 0:
        return "n=0"
    tag = " " if b["n"] >= MIN_SAMPLES else "*"
    return (f"{tag}n={b['n']:3d}  hit={b['hit_rate']}  "
            f"expR={b['exp_R_cons']:+.2f}/{b['exp_R_opt']:+.2f}  "
            f"gain={b['avg_gain']}%  loss={b['avg_loss']}%")


def main() -> None:
    recs = _load()
    res  = _resolved(recs)
    print("=" * 72)
    print(f"SIGNAL ANALYTICS — {len(recs)} signals, {len(res)} resolved")
    print("=" * 72)
    if not res:
        print("No resolved outcomes yet. Run run_consensus_outcome_backfill.py after market close.")
        return

    overall  = _bucket(res)
    by_setup = _by(res, lambda r: r.get("setup_type") or "NONE")
    by_band  = _by(res, lambda r: f"{int(float(r.get('final_trade_score_v3') or 0)//5*5)}-{int(float(r.get('final_trade_score_v3') or 0)//5*5)+5}")
    by_state = _by(res, lambda r: r.get("signal_state") or "NONE")
    by_tier  = _by(res, lambda r: r.get("tier") or "?")
    by_votes = _by(res, lambda r: r.get("vote_count"))
    by_hour  = _by(res, _hour)
    calib    = _calibration(res)
    feat     = _feature_edge(res)
    recommend = _recommend(overall, by_setup, by_state, by_tier, calib, feat)

    print(f"\nOVERALL  {_fmt(overall)}")
    print("  (expR shown as conservative/optimistic — true expectancy is between)")

    def section(title, d):
        print(f"\n── {title} " + "─" * (60 - len(title)))
        for k, b in sorted(d.items(), key=lambda kv: -(kv[1]['exp_R_cons'] or -9)):
            print(f"  {k:<16} {_fmt(b)}")

    section("By setup", by_setup)
    section("By score band", by_band)
    section("By signal state", by_state)
    section("By tier", by_tier)
    section("By vote count", by_votes)
    section("By hour (ET)", by_hour)

    if calib:
        print("\n── Calibration (predicted vs actual win rate) ──────────────")
        for c in calib:
            flag = "  ⚠ over-confident" if c["gap"] < -0.15 and c["n"] >= MIN_SAMPLES else ""
            print(f"  conf {c['band']:<7} n={c['n']:3d}  predicted={c['predicted']}  actual={c['actual']}  gap={c['gap']:+.2f}{flag}")

    if feat:
        print("\n── Feature edge (winner mean vs loser mean) ────────────────")
        for f in feat:
            print(f"  {f['feature']:<28} win={f['win_mean']:>8.2f}  lose={f['lose_mean']:>8.2f}  sep={f['separation']:+.2f}")

    print("\n" + "=" * 72)
    print("RECOMMENDATIONS")
    print("=" * 72)
    for i, r in enumerate(recommend, 1):
        print(f"  {i}. {r}")

    OUT.write_text(json.dumps({
        "generated_at": datetime.now(ET).isoformat(),
        "total": len(recs), "resolved": len(res),
        "overall": overall, "by_setup": by_setup, "by_score_band": by_band,
        "by_state": by_state, "by_tier": by_tier, "by_votes": by_votes,
        "by_hour": by_hour, "calibration": calib, "feature_edge": feat,
        "recommendations": recommend,
    }, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
