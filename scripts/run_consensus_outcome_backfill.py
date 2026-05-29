"""
Consensus Outcome Backfill
==========================
Reads state/consensus_outcomes.jsonl and fills in outcome_* fields by
fetching real prices from Alpaca for any record whose outcomes are still
null AND whose signal timestamp is old enough (≥30 min for outcome_price_30m,
≥60 min for outcome_price_60m, after market close for outcome_price_eod).

Run as cron every 5 minutes during market hours; final sweep after close.

Usage (from jini root):
    PYTHONPATH=src python3 scripts/run_consensus_outcome_backfill.py
    PYTHONPATH=src python3 scripts/run_consensus_outcome_backfill.py --dry-run
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

JINI_ROOT     = Path(__file__).resolve().parent.parent
OUTCOMES_LOG  = JINI_ROOT / "state" / "consensus_outcomes.jsonl"
ET            = ZoneInfo("America/New_York")

TARGET_GAIN_PCT = 0.90   # the v3 RR target (target reached = hit)
STOP_LOSS_PCT   = 0.60   # the v3 stop

# Load .env
def _load_env() -> None:
    dotenv = JINI_ROOT / ".env"
    if not dotenv.exists():
        return
    for line in dotenv.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def _alpaca_client():
    """Return an Alpaca historical data client; None if SDK not available."""
    try:
        from alpaca.data.historical import StockHistoricalDataClient
    except ImportError:
        print("ERROR: alpaca-py not installed (pip3 install alpaca-py)")
        return None
    key    = os.environ.get("ALPACA_API_KEY") or os.environ.get("APCA_API_KEY_ID")
    secret = os.environ.get("ALPACA_SECRET_KEY") or os.environ.get("APCA_API_SECRET_KEY")
    if not key or not secret:
        print("ERROR: Alpaca keys not in env (ALPACA_API_KEY/ALPACA_SECRET_KEY)")
        return None
    return StockHistoricalDataClient(key, secret)


def _bars_between(client, ticker: str, start: datetime, end: datetime) -> list:
    from alpaca.data.requests   import StockBarsRequest
    from alpaca.data.timeframe  import TimeFrame
    req = StockBarsRequest(
        symbol_or_symbols=ticker,
        timeframe=TimeFrame.Minute,
        start=start,
        end=end,
        feed="iex",  # safe default; switch to "sip" if you have the subscription
    )
    try:
        resp = client.get_stock_bars(req)
        return list(resp.data.get(ticker, []))
    except Exception as e:
        print(f"  fetch error for {ticker}: {e}")
        return []


def _price_at_or_after(bars: list, when: datetime) -> float | None:
    """First bar close at or after the given time."""
    for b in bars:
        if b.timestamp >= when:
            return float(b.close)
    return float(bars[-1].close) if bars else None


def _max_excursion(bars: list, entry: float) -> tuple[float | None, float | None]:
    """Return (max_pct_gain, max_pct_loss) across all bars vs entry."""
    if not bars or entry <= 0:
        return None, None
    highs = [float(b.high) for b in bars]
    lows  = [float(b.low)  for b in bars]
    max_gain = max((h - entry) / entry * 100 for h in highs)
    max_loss = min((l - entry) / entry * 100 for l in lows)
    return round(max_gain, 3), round(max_loss, 3)


def _process_record(record: dict, client, dry_run: bool) -> tuple[dict, bool]:
    """Fill any missing outcome fields. Returns (record, changed)."""
    ticker = record.get("ticker")
    entry  = record.get("entry_price")
    if not ticker or entry is None:
        return record, False

    sig_time = datetime.fromisoformat(record["timestamp"])
    if sig_time.tzinfo is None:
        sig_time = sig_time.replace(tzinfo=ET)
    now = datetime.now(ET)

    # EOD = 16:00 ET of the signal's trading day
    eod = sig_time.replace(hour=16, minute=0, second=0, microsecond=0)

    # What can we backfill?
    needs_30m  = record.get("outcome_price_30m") is None and now >= sig_time + timedelta(minutes=30)
    needs_60m  = record.get("outcome_price_60m") is None and now >= sig_time + timedelta(minutes=60)
    needs_eod  = record.get("outcome_price_eod") is None and now >= eod

    if not (needs_30m or needs_60m or needs_eod):
        return record, False

    end_target = eod if needs_eod else now
    bars = _bars_between(client, ticker, sig_time, end_target)
    if not bars:
        return record, False

    changed = False
    if needs_30m:
        p = _price_at_or_after(bars, sig_time + timedelta(minutes=30))
        if p is not None:
            record["outcome_price_30m"] = round(p, 4); changed = True
    if needs_60m:
        p = _price_at_or_after(bars, sig_time + timedelta(minutes=60))
        if p is not None:
            record["outcome_price_60m"] = round(p, 4); changed = True
    if needs_eod:
        p = _price_at_or_after(bars, eod - timedelta(minutes=1))
        if p is not None:
            record["outcome_price_eod"] = round(p, 4); changed = True

    # Compute max excursion + hit flags once we have a full window
    if needs_eod or needs_60m:
        gain, loss = _max_excursion(bars, entry)
        if gain is not None:
            record["outcome_max_pct_gain"] = gain
            record["outcome_max_pct_loss"] = loss
            record["outcome_hit_target"]   = gain >= TARGET_GAIN_PCT and loss > -STOP_LOSS_PCT

            # If a trade plan was logged, check whether T1 / T2 were actually reached
            day_high = max(float(b.high) for b in bars)
            t1 = record.get("plan_target1")
            t2 = record.get("plan_target2")
            if t1:
                record["outcome_hit_t1"] = day_high >= float(t1)
            if t2:
                record["outcome_hit_t2"] = day_high >= float(t2)
            changed = True

    if changed and not dry_run:
        record["outcome_filled_at"] = datetime.now(ET).isoformat()

    return record, changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill outcome fields in consensus_outcomes.jsonl")
    parser.add_argument("--dry-run", action="store_true", help="Don't write changes")
    args = parser.parse_args()

    if not OUTCOMES_LOG.exists():
        print(f"No log at {OUTCOMES_LOG} — nothing to backfill.")
        return

    _load_env()
    client = _alpaca_client()
    if client is None:
        sys.exit(1)

    records = [json.loads(line) for line in OUTCOMES_LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"Loaded {len(records)} records from {OUTCOMES_LOG}")

    changed_count = 0
    for i, rec in enumerate(records):
        rec, changed = _process_record(rec, client, dry_run=args.dry_run)
        if changed:
            changed_count += 1
            t = rec.get("ticker")
            print(
                f"  [{i+1}/{len(records)}] {t}: "
                f"30m={rec.get('outcome_price_30m')} "
                f"60m={rec.get('outcome_price_60m')} "
                f"eod={rec.get('outcome_price_eod')} "
                f"max+={rec.get('outcome_max_pct_gain')}% "
                f"hit={rec.get('outcome_hit_target')}"
            )

    print(f"\nFilled outcomes for {changed_count} record(s).")
    if changed_count and not args.dry_run:
        tmp = OUTCOMES_LOG.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")
        tmp.replace(OUTCOMES_LOG)
        print(f"Rewrote {OUTCOMES_LOG}")


if __name__ == "__main__":
    main()
