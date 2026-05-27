"""
Consensus Aggregator (elite refinement)
=======================================
Runs engine2 + engine3 IN PARALLEL, caches their output for 5 minutes,
reads jini's enriched rows, finds consensus tickers, gates them through
jini's full v3 scoring pipeline, and writes both a human-readable
report AND a structured JSON file for the model2 dashboard.

Usage (from jini root):
    PYTHONPATH=src python3 scripts/run_consensus_aggregator.py
    PYTHONPATH=src python3 scripts/run_consensus_aggregator.py --threshold 3
    PYTHONPATH=src python3 scripts/run_consensus_aggregator.py --no-cache

Outputs:
  - Console: vote table + final picks
  - state/consensus_picks_live.json: structured snapshot for dashboards
  - state/consensus_outcomes.jsonl: append-only log for outcome tracking
"""

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# ── Repo layout ────────────────────────────────────────────────────────────
JINI_ROOT = Path(__file__).resolve().parent.parent
E1V32     = JINI_ROOT.parent

ENGINE_DIRS = {
    "engine2": E1V32 / "engine2",
    "engine3": E1V32 / "engine3",
}

# ── Tunables ───────────────────────────────────────────────────────────────
DEFAULT_THRESHOLD     = 2
DEFAULT_MIN_SCORE     = 65.0
ENRICHED_MAX_AGE_H    = 4
CACHE_MAX_AGE_SEC     = 300       # use cached engine output if newer than 5 min
ENGINE2_TIMEOUT_SEC   = 300
ENGINE3_TIMEOUT_SEC   = 180

ENRICHED_PATH = JINI_ROOT / "state" / "prediction_engine" / "v3_enriched_rows.json"
OUTCOMES_LOG  = JINI_ROOT / "state" / "consensus_outcomes.jsonl"
LIVE_PICKS    = JINI_ROOT / "state" / "consensus_picks_live.json"
SCORECARD     = JINI_ROOT / "state" / "consensus_scorecard.json"


# ═══════════════════════════════════════════════════════════════════════════
# Utilities
# ═══════════════════════════════════════════════════════════════════════════

def _sym(row: dict) -> str:
    return (row.get("ticker") or row.get("symbol") or "").strip().upper()


def _market_is_open() -> bool:
    """NYSE regular hours Mon–Fri 09:30–16:00 ET."""
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    open_t  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    close_t = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    return open_t <= now <= close_t


def _build_env() -> dict:
    """Merge jini's .env into the current environment so subprocesses inherit API keys."""
    env = os.environ.copy()
    dotenv = JINI_ROOT / ".env"
    if not dotenv.exists():
        return env
    for line in dotenv.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in env:
            env[key] = val
    return env


def _file_age_sec(path: Path) -> float:
    if not path.exists():
        return float("inf")
    return time.time() - path.stat().st_mtime


def _load_engine_weights() -> dict[str, float]:
    """Read per-engine hit rates from the scorecard; default 1.0 for unmeasured engines."""
    if not SCORECARD.exists():
        return {}
    try:
        data = json.loads(SCORECARD.read_text(encoding="utf-8"))
        return {name: float(s.get("weight", 1.0)) for name, s in data.get("engines", {}).items()}
    except Exception:
        return {}


# ═══════════════════════════════════════════════════════════════════════════
# Engine adapters — each returns (engine_name, set[str] of tickers, diagnostic_str)
# ═══════════════════════════════════════════════════════════════════════════

def _adapter_jini() -> tuple[str, set[str], str]:
    if not ENRICHED_PATH.exists():
        return "jini", set(), "SKIP — enriched rows not found"

    age_h = _file_age_sec(ENRICHED_PATH) / 3600
    diag  = f"{age_h:.1f}h old"
    if age_h > ENRICHED_MAX_AGE_H:
        diag = f"WARNING — enriched rows are {diag} (>{ENRICHED_MAX_AGE_H}h)"

    try:
        data = json.loads(ENRICHED_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        return "jini", set(), f"ERROR reading enriched rows: {e}"

    rows = data if isinstance(data, list) else data.get("rows", data.get("candidates", []))
    tickers = {_sym(r) for r in rows if _sym(r)}
    return "jini", tickers, f"{len(tickers)} enriched candidates ({diag})"


def _adapter_engine2(use_cache: bool) -> tuple[str, set[str], str]:
    eng_dir = ENGINE_DIRS["engine2"]
    if not eng_dir.exists():
        return "engine2", set(), f"SKIP — not cloned at {eng_dir}"

    signals_file = eng_dir / "docs" / "data" / "signals.json"

    # Cache check — skip subprocess if signals file is fresh
    age = _file_age_sec(signals_file)
    if use_cache and age < CACHE_MAX_AGE_SEC:
        tickers = _read_engine2_picks(signals_file)
        return "engine2", tickers, f"cached ({age:.0f}s old) — {len(tickers)} BUY SETUP"

    # Market hours guard — engine2 hangs when market is closed
    if not _market_is_open():
        return "engine2", set(), "SKIP — market closed (engine2 hangs)"

    scanner_script = eng_dir / "src" / "scanner.py"
    if not scanner_script.exists():
        return "engine2", set(), "SKIP — src/scanner.py missing"

    try:
        result = subprocess.run(
            [sys.executable, "-m", "src.scanner"],
            cwd=str(eng_dir),
            capture_output=True,
            text=True,
            timeout=ENGINE2_TIMEOUT_SEC,
            env=_build_env(),
            check=False,
        )
        if result.returncode != 0:
            stderr_tail = result.stderr.strip()[-600:] if result.stderr else "(no stderr)"
            return "engine2", set(), f"exited {result.returncode} — {stderr_tail}"
    except subprocess.TimeoutExpired:
        return "engine2", set(), f"TIMEOUT after {ENGINE2_TIMEOUT_SEC}s"
    except Exception as e:
        return "engine2", set(), f"ERROR: {e}"

    tickers = _read_engine2_picks(signals_file)
    return "engine2", tickers, f"{len(tickers)} BUY SETUP tickers"


def _read_engine2_picks(signals_file: Path) -> set[str]:
    if not signals_file.exists():
        return set()
    try:
        payload = json.loads(signals_file.read_text(encoding="utf-8"))
    except Exception:
        return set()
    signals = payload.get("signals", payload) if isinstance(payload, dict) else payload
    return {
        _sym(s) for s in signals
        if isinstance(s, dict) and s.get("decision") == "BUY SETUP" and _sym(s)
    }


def _adapter_engine3(use_cache: bool) -> tuple[str, set[str], str]:
    eng_dir = ENGINE_DIRS["engine3"]
    if not eng_dir.exists():
        return "engine3", set(), f"SKIP — not cloned at {eng_dir}"

    picks_file = eng_dir / "docs" / "data" / "picks.json"
    age = _file_age_sec(picks_file)
    if use_cache and age < CACHE_MAX_AGE_SEC:
        tickers = _read_engine3_picks(picks_file)
        return "engine3", tickers, f"cached ({age:.0f}s old) — {len(tickers)} signal tickers"

    main_script = eng_dir / "src" / "main.py"
    if not main_script.exists():
        return "engine3", set(), "SKIP — src/main.py missing"

    try:
        result = subprocess.run(
            [sys.executable, str(main_script)],
            cwd=str(eng_dir),
            capture_output=True,
            text=True,
            timeout=ENGINE3_TIMEOUT_SEC,
            env=_build_env(),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "engine3", set(), f"TIMEOUT after {ENGINE3_TIMEOUT_SEC}s"
    except Exception as e:
        return "engine3", set(), f"ERROR: {e}"

    # engine3 writes picks.json AND prints summary JSON to stdout
    tickers = _read_engine3_picks(picks_file)
    if not tickers and result.stdout.strip():
        # Fall back to parsing stdout if picks.json is empty
        try:
            data = json.loads(result.stdout.strip())
            signals = data.get("signals", [])
            tickers = {_sym(s) for s in signals if isinstance(s, dict) and _sym(s)}
        except json.JSONDecodeError:
            pass

    diag = f"{len(tickers)} signal tickers"
    if result.returncode != 0:
        diag += f" (exit {result.returncode})"
    return "engine3", tickers, diag


def _read_engine3_picks(picks_file: Path) -> set[str]:
    if not picks_file.exists():
        return set()
    try:
        data = json.loads(picks_file.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if isinstance(data, list):
        picks = data
    elif isinstance(data, dict):
        picks = data.get("picks", data.get("signals", []))
    else:
        return set()
    return {_sym(p) for p in picks if isinstance(p, dict) and _sym(p)}


# ═══════════════════════════════════════════════════════════════════════════
# Parallel runner
# ═══════════════════════════════════════════════════════════════════════════

def _run_engines_parallel(use_cache: bool) -> dict[str, set[str]]:
    """Run jini, engine2, engine3 concurrently and collect their tickers."""
    tasks = {
        "jini":    _adapter_jini,
        "engine2": lambda: _adapter_engine2(use_cache),
        "engine3": lambda: _adapter_engine3(use_cache),
    }
    picks: dict[str, set[str]] = {}
    diags: dict[str, str]      = {}

    print(f"\nRunning {len(tasks)} engines in parallel…")
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = {pool.submit(fn): name for name, fn in tasks.items()}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                eng_name, tickers, diag = fut.result()
            except Exception as e:
                eng_name, tickers, diag = name, set(), f"ADAPTER CRASH: {e}"
            picks[eng_name] = tickers
            diags[eng_name] = diag
            elapsed = time.time() - t0
            print(f"  [{elapsed:5.1f}s] {eng_name:<8} → {diag}")

    return picks


# ═══════════════════════════════════════════════════════════════════════════
# jini v3 scoring gate
# ═══════════════════════════════════════════════════════════════════════════

def _score_with_jini(tickers: set[str], min_score: float) -> list[dict]:
    if not ENRICHED_PATH.exists() or not tickers:
        return []

    data = json.loads(ENRICHED_PATH.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else data.get("rows", data.get("candidates", []))
    rows = [r for r in rows if _sym(r) in tickers]
    if not rows:
        return []

    try:
        from prediction_engine.scoring.runner_potential_v3   import RunnerPotentialScorerV3
        from prediction_engine.scoring.entry_quality_v3      import EntryQualityScorerV3
        from prediction_engine.scoring.danger_score_v3       import DangerScoreScorerV3
        from prediction_engine.scoring.final_trade_score_v3  import FinalTradeScoreScorerV3
    except ImportError as e:
        print(f"[jini v3] ImportError: {e}\n  Use: PYTHONPATH=src python3 scripts/run_consensus_aggregator.py")
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
# Outputs
# ═══════════════════════════════════════════════════════════════════════════

def _write_live_picks(
    picks: list[dict],
    vote_counts: dict[str, int],
    engine_picks: dict[str, set[str]],
    threshold: int,
    min_score: float,
) -> None:
    """Structured snapshot for the model2 dashboard and other consumers."""
    LIVE_PICKS.parent.mkdir(parents=True, exist_ok=True)
    now_et = datetime.now(ZoneInfo("America/New_York")).isoformat()
    weights = _load_engine_weights()

    vote_table = [
        {
            "ticker":  ticker,
            "votes":   votes,
            "sources": sorted(n for n, p in engine_picks.items() if ticker in p),
        }
        for ticker, votes in sorted(vote_counts.items(), key=lambda x: (-x[1], x[0]))
    ]

    enriched_picks = []
    for sig in picks:
        ticker  = _sym(sig)
        sources = sorted(n for n, p in engine_picks.items() if ticker in p)
        enriched_picks.append({
            "ticker":                        ticker,
            "final_trade_score_v3":          sig.get("final_trade_score_v3"),
            "final_trade_score_status_v3":   sig.get("final_trade_score_status_v3"),
            "runner_potential_v3":           sig.get("runner_potential_v3"),
            "entry_quality_v3":              sig.get("entry_quality_v3"),
            "danger_score_v3":               sig.get("danger_score_v3"),
            "price":                         sig.get("price"),
            "relative_volume":               sig.get("relative_volume"),
            "vwap_distance_pct":             sig.get("vwap_distance_pct"),
            "momentum_1m":                   sig.get("momentum_1m"),
            "candle_strength":               sig.get("candle_strength"),
            "vote_count":                    vote_counts.get(ticker, 0),
            "vote_sources":                  sources,
            "weighted_score":                round(
                float(sig.get("final_trade_score_v3", 0))
                + sum(weights.get(s, 1.0) for s in sources) * 5.0,
                2,
            ),
        })
    enriched_picks.sort(key=lambda p: p["weighted_score"] or 0, reverse=True)

    payload = {
        "schema_version":  "consensus_picks_v1",
        "generated_at":    now_et,
        "market_open":     _market_is_open(),
        "active_engines":  [n for n, p in engine_picks.items() if p],
        "threshold":       threshold,
        "min_score":       min_score,
        "engine_weights":  weights,
        "vote_table":      vote_table,
        "consensus_picks": enriched_picks,
    }
    LIVE_PICKS.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n[live]  wrote {LIVE_PICKS}")


def _log_outcomes(signals: list[dict], vote_counts: dict[str, int],
                  engine_picks: dict[str, set[str]]) -> None:
    if not signals:
        return
    OUTCOMES_LOG.parent.mkdir(parents=True, exist_ok=True)
    now_et = datetime.now(ZoneInfo("America/New_York")).isoformat()
    with OUTCOMES_LOG.open("a", encoding="utf-8") as fh:
        for sig in signals:
            ticker = _sym(sig)
            sources = sorted(n for n, p in engine_picks.items() if ticker in p)
            record = {
                "timestamp":                   now_et,
                "ticker":                      ticker,
                "vote_count":                  vote_counts.get(ticker, 0),
                "vote_sources":                sources,
                "final_trade_score_v3":        sig.get("final_trade_score_v3"),
                "final_trade_score_status_v3": sig.get("final_trade_score_status_v3"),
                "runner_potential_v3":         sig.get("runner_potential_v3"),
                "entry_quality_v3":            sig.get("entry_quality_v3"),
                "danger_score_v3":             sig.get("danger_score_v3"),
                "entry_price":                 sig.get("price"),
                "vwap_distance_pct_at_signal": sig.get("vwap_distance_pct"),
                "relative_volume_at_signal":   sig.get("relative_volume"),
                "outcome_hit_target":          None,
                "outcome_price_30m":           None,
                "outcome_price_60m":           None,
                "outcome_price_eod":           None,
                "outcome_max_pct_gain":        None,
                "outcome_max_pct_loss":        None,
                "outcome_filled_at":           None,
            }
            fh.write(json.dumps(record) + "\n")
    print(f"[log]   {len(signals)} signal(s) appended → {OUTCOMES_LOG}")


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="Elite consensus aggregator for jini")
    parser.add_argument("--threshold", type=int,   default=DEFAULT_THRESHOLD)
    parser.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    parser.add_argument("--no-cache",  action="store_true",
                        help="Force re-running engines, ignoring cached signal files")
    args = parser.parse_args()

    print("=" * 60)
    print(f"CONSENSUS AGGREGATOR  |  threshold={args.threshold}  min_score={args.min_score}")
    print(f"market_open={_market_is_open()}  cache={'off' if args.no_cache else 'on'}")
    print("=" * 60)

    # ── 1. Run all engines in parallel ──────────────────────────────────
    engine_picks = _run_engines_parallel(use_cache=not args.no_cache)

    active = [n for n, p in engine_picks.items() if p]
    if not active:
        print("\nNo engine returned candidates.")
        _write_live_picks([], {}, engine_picks, args.threshold, args.min_score)
        return

    # ── 2. Count votes (weighted by historical accuracy) ────────────────
    weights = _load_engine_weights()
    vote_counts: dict[str, int]    = {}
    weighted_votes: dict[str, float] = {}
    for engine, picks in engine_picks.items():
        w = weights.get(engine, 1.0)
        for ticker in picks:
            vote_counts[ticker]    = vote_counts.get(ticker, 0) + 1
            weighted_votes[ticker] = weighted_votes.get(ticker, 0.0) + w

    consensus = {t for t, v in vote_counts.items() if v >= args.threshold}

    print(f"\n── Vote table ({len(active)} active engine(s)) ─────────────")
    for ticker, votes in sorted(vote_counts.items(),
                                 key=lambda x: (-weighted_votes[x[0]], -x[1], x[0]))[:30]:
        sources = sorted(n for n, p in engine_picks.items() if ticker in p)
        mark = " ✓ CONSENSUS" if ticker in consensus else ""
        wv = weighted_votes[ticker]
        print(f"  {ticker:<8} {votes}/{len(active)} (w={wv:.1f})  [{', '.join(sources)}]{mark}")
    if len(vote_counts) > 30:
        print(f"  … and {len(vote_counts) - 30} more")

    # ── 3. Gate through jini v3 ─────────────────────────────────────────
    buy_signals = _score_with_jini(consensus, args.min_score) if consensus else []

    if buy_signals:
        now = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
        print(f"\n{'='*60}\nFINAL PICKS ({len(buy_signals)})  —  {now}\n{'='*60}")
        for sig in buy_signals:
            ticker = _sym(sig)
            score  = float(sig.get("final_trade_score_v3", 0))
            status = sig.get("final_trade_score_status_v3", "")
            runner = float(sig.get("runner_potential_v3",   0))
            entry  = float(sig.get("entry_quality_v3",      0))
            danger = float(sig.get("danger_score_v3",       0))
            price  = float(sig.get("price",                 0))
            rvol   = float(sig.get("relative_volume",       0))
            sources = sorted(n for n, p in engine_picks.items() if ticker in p)
            print(
                f"  {ticker:<8} score={score:5.1f} ({status})  "
                f"R={runner:4.0f} E={entry:4.0f} D={danger:4.0f}  "
                f"${price:>6.2f}  rvol={rvol:.1f}x  [{', '.join(sources)}]"
            )
    elif consensus:
        print("\nNo consensus ticker passed jini's v3 gate.")
    else:
        print(f"\nNo ticker reached the {args.threshold}-vote threshold.")

    # ── 4. Persist outputs ──────────────────────────────────────────────
    _write_live_picks(buy_signals, vote_counts, engine_picks, args.threshold, args.min_score)
    _log_outcomes(buy_signals, vote_counts, engine_picks)


if __name__ == "__main__":
    main()
