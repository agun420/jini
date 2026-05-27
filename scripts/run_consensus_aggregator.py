"""
Consensus Aggregator
====================
Runs engine2 and engine3 as subprocesses, reads jini's own enriched rows,
counts per-ticker votes, then gates the consensus through jini's full v3
scoring pipeline before emitting final picks.

Usage (from jini root):
    python scripts/run_consensus_aggregator.py [--threshold N] [--min-score F]

Requires:
  - engine2 cloned at  ../engine2/   (relative to this jini repo)
  - engine3 cloned at  ../engine3/   (relative to this jini repo)
  - jini's run_alpaca_v3_market_enrichment.py must have been run today
    (state/prediction_engine/v3_enriched_rows.json must exist and be fresh)

Output:
  - Console: final picks with all score fields
  - state/consensus_outcomes.jsonl: every emitted signal with blank
    outcome_* fields for you to fill in after the session
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# ── Repo layout ────────────────────────────────────────────────────────────
JINI_ROOT = Path(__file__).resolve().parent.parent
E1V32     = JINI_ROOT.parent          # e.g. ~/Downloads/e1v32/

ENGINE_DIRS = {
    "engine2": E1V32 / "engine2",
    "engine3": E1V32 / "engine3",
}

# ── Tunable constants ──────────────────────────────────────────────────────
DEFAULT_THRESHOLD   = 2      # engines that must agree before jini scores
DEFAULT_MIN_SCORE   = 65.0   # minimum final_trade_score_v3 to emit
ENRICHED_MAX_AGE_H  = 4      # warn if enriched rows are older than this

ENRICHED_PATH   = JINI_ROOT / "state" / "prediction_engine" / "v3_enriched_rows.json"
OUTCOMES_LOG    = JINI_ROOT / "state" / "consensus_outcomes.jsonl"


# ═══════════════════════════════════════════════════════════════════════════
# Engine adapters — each returns a set[str] of ticker symbols
# ═══════════════════════════════════════════════════════════════════════════

def _adapter_jini() -> set[str]:
    """Tickers present in jini's most recent enriched rows."""
    if not ENRICHED_PATH.exists():
        print("[jini]  SKIP — enriched rows not found; run run_alpaca_v3_market_enrichment.py first")
        return set()

    age_h = (datetime.now(timezone.utc).timestamp() - ENRICHED_PATH.stat().st_mtime) / 3600
    if age_h > ENRICHED_MAX_AGE_H:
        print(f"[jini]  WARNING — enriched rows are {age_h:.1f}h old (threshold {ENRICHED_MAX_AGE_H}h)")

    try:
        data = json.loads(ENRICHED_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[jini]  ERROR reading enriched rows: {e}")
        return set()

    rows = data if isinstance(data, list) else data.get("rows", data.get("candidates", []))
    tickers = {_sym(r) for r in rows if _sym(r)}
    print(f"[jini]  {len(tickers)} enriched candidates")
    return tickers


def _adapter_engine2() -> set[str]:
    """BUY SETUP tickers from engine2 (runs engine2 as subprocess)."""
    eng_dir = ENGINE_DIRS["engine2"]
    if not eng_dir.exists():
        print(f"[engine2] SKIP — not cloned at {eng_dir}")
        return set()

    scanner_script = eng_dir / "src" / "scanner.py"
    if not scanner_script.exists():
        print(f"[engine2] SKIP — src/scanner.py not found in {eng_dir}")
        return set()

    print("[engine2] running scanner…")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "src.scanner"],
            cwd=str(eng_dir),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            print(f"[engine2] exited {result.returncode}")
        if result.stderr.strip():
            print(f"[engine2] stderr: {result.stderr.strip()[:400]}")
    except subprocess.TimeoutExpired:
        print("[engine2] TIMEOUT after 120s")
        return set()
    except Exception as e:
        print(f"[engine2] ERROR: {e}")
        return set()

    signals_file = eng_dir / "docs" / "data" / "signals.json"
    if not signals_file.exists():
        print("[engine2] signals.json not produced")
        return set()

    try:
        payload = json.loads(signals_file.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[engine2] ERROR reading signals.json: {e}")
        return set()

    signals = payload.get("signals", payload) if isinstance(payload, dict) else payload
    tickers = {
        _sym(s) for s in signals
        if isinstance(s, dict) and s.get("decision") == "BUY SETUP" and _sym(s)
    }
    print(f"[engine2] {len(tickers)} BUY SETUP tickers: {sorted(tickers)}")
    return tickers


def _adapter_engine3() -> set[str]:
    """Signal tickers from engine3 (runs engine3, parses stdout JSON)."""
    eng_dir = ENGINE_DIRS["engine3"]
    if not eng_dir.exists():
        print(f"[engine3] SKIP — not cloned at {eng_dir}")
        return set()

    main_script = eng_dir / "src" / "main.py"
    if not main_script.exists():
        print(f"[engine3] SKIP — src/main.py not found in {eng_dir}")
        return set()

    print("[engine3] running main…")
    try:
        result = subprocess.run(
            [sys.executable, str(main_script)],
            cwd=str(eng_dir),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print("[engine3] TIMEOUT after 180s")
        return set()
    except Exception as e:
        print(f"[engine3] ERROR: {e}")
        return set()

    if result.returncode != 0:
        print(f"[engine3] exited {result.returncode}")
    if result.stderr.strip():
        print(f"[engine3] stderr: {result.stderr.strip()[:600]}")

    stdout = result.stdout.strip()
    if not stdout:
        print("[engine3] no stdout — likely crashed on startup (see stderr above)")
        return set()

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        # engine3 might prepend log lines before the JSON — find the first '{'
        idx = stdout.find("{")
        if idx == -1:
            print("[engine3] could not parse JSON from stdout")
            return set()
        try:
            data = json.loads(stdout[idx:])
        except json.JSONDecodeError as e:
            print(f"[engine3] JSON parse error: {e}")
            return set()

    signals = data.get("signals", [])
    tickers = {_sym(s) for s in signals if isinstance(s, dict) and _sym(s)}
    print(f"[engine3] {len(tickers)} signal tickers: {sorted(tickers)}")
    return tickers


# ═══════════════════════════════════════════════════════════════════════════
# jini v3 scoring gate
# ═══════════════════════════════════════════════════════════════════════════

def _score_with_jini(tickers: set[str], min_score: float) -> list[dict]:
    """
    Load enriched rows for the given tickers and run jini's full v3 pipeline.
    Returns only rows where buy_order_alert_candidate_v3 is True and
    final_trade_score_v3 >= min_score.
    """
    if not ENRICHED_PATH.exists():
        return []

    data = json.loads(ENRICHED_PATH.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else data.get("rows", data.get("candidates", []))
    rows = [r for r in rows if _sym(r) in tickers]

    if not rows:
        print("[jini v3] no enriched rows matched the consensus tickers")
        return []

    print(f"[jini v3] scoring {len(rows)} consensus rows…")

    try:
        from prediction_engine.scoring.runner_potential_v3 import RunnerPotentialScorerV3
        from prediction_engine.scoring.entry_quality_v3   import EntryQualityScorerV3
        from prediction_engine.scoring.danger_score_v3    import DangerScoreScorerV3
        from prediction_engine.scoring.final_trade_score_v3 import FinalTradeScoreScorerV3
    except ImportError as e:
        print(
            f"[jini v3] ImportError: {e}\n"
            "          Run from jini root and ensure the package is on PYTHONPATH:\n"
            "          PYTHONPATH=src python scripts/run_consensus_aggregator.py"
        )
        return []

    rows = RunnerPotentialScorerV3().score(rows)
    rows = EntryQualityScorerV3().score(rows)
    rows = DangerScoreScorerV3().score(rows)
    rows = FinalTradeScoreScorerV3().score(rows)

    return [
        r for r in rows
        if r.get("buy_order_alert_candidate_v3")
        and float(r.get("final_trade_score_v3", 0)) >= min_score
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Outcome logger
# ═══════════════════════════════════════════════════════════════════════════

def _log_signals(signals: list[dict], vote_counts: dict[str, int]) -> None:
    now_et = datetime.now(ZoneInfo("America/New_York")).isoformat()
    OUTCOMES_LOG.parent.mkdir(parents=True, exist_ok=True)

    with OUTCOMES_LOG.open("a", encoding="utf-8") as fh:
        for sig in signals:
            ticker = _sym(sig)
            record = {
                "timestamp":                   now_et,
                "ticker":                      ticker,
                "vote_count":                  vote_counts.get(ticker, 0),
                "final_trade_score_v3":        sig.get("final_trade_score_v3"),
                "final_trade_score_status_v3": sig.get("final_trade_score_status_v3"),
                "runner_potential_v3":          sig.get("runner_potential_v3"),
                "entry_quality_v3":            sig.get("entry_quality_v3"),
                "danger_score_v3":             sig.get("danger_score_v3"),
                "price":                       sig.get("price"),
                "vwap_distance_pct":           sig.get("vwap_distance_pct"),
                "relative_volume":             sig.get("relative_volume"),
                "momentum_1m":                 sig.get("momentum_1m"),
                "candle_strength":             sig.get("candle_strength"),
                # ── fill these in after the session ──────────────────────
                "outcome_hit_target":  None,   # True / False
                "outcome_price_30m":   None,   # price 30 min after signal
                "outcome_price_eod":   None,   # price at EOD
                "outcome_notes":       None,   # free text
            }
            fh.write(json.dumps(record) + "\n")

    print(f"[log]   {len(signals)} signal(s) appended → {OUTCOMES_LOG}")


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _sym(row: dict) -> str:
    return (row.get("ticker") or row.get("symbol") or "").strip().upper()


def _banner(msg: str) -> None:
    print(f"\n{'='*60}\n{msg}\n{'='*60}")


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-engine consensus aggregator for jini")
    parser.add_argument("--threshold", type=int,   default=DEFAULT_THRESHOLD,
                        help=f"Min engine agreement count (default {DEFAULT_THRESHOLD})")
    parser.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE,
                        help=f"Min final_trade_score_v3 (default {DEFAULT_MIN_SCORE})")
    args = parser.parse_args()

    _banner(f"CONSENSUS AGGREGATOR  |  threshold={args.threshold}  min_score={args.min_score}")

    # ── 1. Run all engines ──────────────────────────────────────────────
    adapters = [
        ("jini",    _adapter_jini),
        ("engine2", _adapter_engine2),
        ("engine3", _adapter_engine3),
    ]

    engine_picks: dict[str, set[str]] = {}
    for name, fn in adapters:
        engine_picks[name] = fn()

    active_engines = [n for n, picks in engine_picks.items() if picks]
    if not active_engines:
        print("\nNo engine returned any candidates. Check API keys and cloned repos.")
        return

    # ── 2. Count votes ──────────────────────────────────────────────────
    vote_counts: dict[str, int] = {}
    for picks in engine_picks.values():
        for ticker in picks:
            vote_counts[ticker] = vote_counts.get(ticker, 0) + 1

    total_engines = len(active_engines)
    consensus = {t for t, v in vote_counts.items() if v >= args.threshold}

    print(f"\n── Vote table ({total_engines} active engine(s)) {'─'*30}")
    for ticker, votes in sorted(vote_counts.items(), key=lambda x: (-x[1], x[0])):
        sources = [n for n, picks in engine_picks.items() if ticker in picks]
        mark = " ✓ CONSENSUS" if ticker in consensus else ""
        print(f"  {ticker:<8} {votes}/{total_engines}  [{', '.join(sources)}]{mark}")

    if not consensus:
        print(f"\nNo ticker reached the {args.threshold}-vote threshold. Done.")
        _log_signals([], vote_counts)
        return

    print(f"\n── Consensus tickers ({len(consensus)}): {sorted(consensus)}")

    # ── 3. Gate through jini v3 ─────────────────────────────────────────
    buy_signals = _score_with_jini(consensus, args.min_score)

    if not buy_signals:
        print("\nNo consensus ticker passed jini's v3 gate today.")
        _log_signals([], vote_counts)
        return

    # ── 4. Print final picks ────────────────────────────────────────────
    now_et = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    _banner(f"FINAL PICKS ({len(buy_signals)})  —  {now_et}")

    for sig in buy_signals:
        ticker  = _sym(sig)
        score   = float(sig.get("final_trade_score_v3",   0))
        status  = sig.get("final_trade_score_status_v3",  "")
        runner  = float(sig.get("runner_potential_v3",    0))
        entry   = float(sig.get("entry_quality_v3",       0))
        danger  = float(sig.get("danger_score_v3",        0))
        price   = float(sig.get("price",                  0))
        rvol    = float(sig.get("relative_volume",        0))
        vwap_d  = float(sig.get("vwap_distance_pct",      0))
        votes   = vote_counts.get(ticker, 0)
        sources = [n for n, picks in engine_picks.items() if ticker in picks]

        print(
            f"  {ticker:<8}"
            f"  score={score:5.1f}  ({status})"
            f"  runner={runner:4.0f}  entry={entry:4.0f}  danger={danger:4.0f}"
            f"  price=${price:.2f}  rvol={rvol:.1f}x  vwap_d={vwap_d:+.2f}%"
            f"  [{votes}/{total_engines}: {', '.join(sources)}]"
        )

    # ── 5. Log to outcomes file ─────────────────────────────────────────
    _log_signals(buy_signals, vote_counts)

    print(
        "\nNext step: after the session, fill in outcome_hit_target / "
        "outcome_price_30m / outcome_price_eod in:\n"
        f"  {OUTCOMES_LOG}\n"
        "After ~50 outcomes you'll know which engine combinations are actually predictive."
    )


if __name__ == "__main__":
    main()
