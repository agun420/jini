"""
Swing Trade Scanner
==================
Daily-timeframe scanner for multi-day / multi-week swing setups — the
complement to the intraday pre-breakout scanner.

Methodology (Minervini SEPA / Weinstein Stage-2 trend template):
  - Stage 2 uptrend: price > 50SMA > 150SMA > 200SMA, 200SMA rising
  - Within 25% of 52-week high, >30% above 52-week low
  - Relative strength vs SPY over 1 & 3 months
  - Volume contraction on base, surge on breakout
  - Setup taxonomy: BREAKOUT, PULLBACK_50MA, FLAT_BASE, EARLY_STAGE2

Entry = pivot above the base. Stop = below 50SMA or base low (wider, swing-sized).
T1 ≈ 2R, T2 ≈ 4R (measured-move / multi-week targets).

Output: state/swing_candidates.json (top ranked with quality_score + trade plan).

Usage:
    PYTHONPATH=src python3 scripts/run_swing_scanner.py
    PYTHONPATH=src python3 scripts/run_swing_scanner.py --min-quality 60
"""

import argparse
import json
import os
import statistics
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

JINI_ROOT = Path(__file__).resolve().parent.parent
ET        = ZoneInfo("America/New_York")
OUTPUT    = JINI_ROOT / "state" / "swing_candidates.json"

sys.path.insert(0, str(JINI_ROOT / "src"))
from prediction_engine.trade_plan import build_trade_plan  # noqa: E402

# Swing universe — liquid, trend-prone names across sectors
DEFAULT_UNIVERSE = [
    "NVDA","AAPL","MSFT","META","GOOGL","AMZN","TSLA","AVGO","AMD","NFLX","ADBE",
    "CRM","ORCL","QCOM","MU","TSM","ARM","PLTR","SMCI","SNOW","DDOG","NET","CRWD",
    "PANW","NOW","ANET","COIN","MSTR","HOOD","SOFI","AFRM","UPST","RKLB","ASTS",
    "MRNA","VRTX","REGN","LLY","UNH","ISRG","BKNG","ABNB","UBER","SHOP","SQ","PYPL",
    "CAT","DE","GE","HON","BA","WMT","COST","HD","LOW","MCD","SBUX","NKE","DIS",
    "JPM","GS","MS","BAC","V","MA","XOM","CVX","COP","FANG","NEM","FCX","LIN",
    "DKNG","CMG","CELH","DELL","TSLA","WDC","ON","LRCX","KLAC","AMAT","MRVL",
    "SPY","QQQ","IWM",
]


def _load_env() -> None:
    dotenv = JINI_ROOT / ".env"
    if not dotenv.exists():
        return
    for line in dotenv.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def _client():
    try:
        from alpaca.data.historical import StockHistoricalDataClient
    except ImportError:
        print("ERROR: alpaca-py not installed (pip3 install alpaca-py)")
        sys.exit(1)
    key    = os.environ.get("ALPACA_API_KEY") or os.environ.get("APCA_API_KEY_ID")
    secret = os.environ.get("ALPACA_SECRET_KEY") or os.environ.get("APCA_API_SECRET_KEY")
    if not key or not secret:
        print("ERROR: Alpaca keys not in env")
        sys.exit(1)
    return StockHistoricalDataClient(key, secret)


def _feed() -> str:
    return os.environ.get("ALPACA_DATA_FEED", "iex").lower()


def _fetch_daily(client, symbols: list[str], days: int = 400) -> dict:
    from alpaca.data.requests  import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    req = StockBarsRequest(
        symbol_or_symbols=symbols, timeframe=TimeFrame.Day,
        start=datetime.now(timezone.utc) - timedelta(days=days),
        end=datetime.now(timezone.utc), feed=_feed(),
    )
    try:
        resp = client.get_stock_bars(req)
        return {s: list(resp.data.get(s, [])) for s in symbols}
    except Exception as e:
        print(f"  daily fetch error: {e}")
        return {}


def _chunked(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def _sma(vals: list[float], period: int) -> Optional[float]:
    return statistics.mean(vals[-period:]) if len(vals) >= period else None


@dataclass
class Swing:
    symbol:          str
    price:           float = 0.0
    sma50:           float = 0.0
    sma150:          float = 0.0
    sma200:          float = 0.0
    sma200_rising:   bool  = False
    pct_from_52w_high: float = 0.0
    pct_above_52w_low: float = 0.0
    rs_1m:           float = 0.0     # vs SPY, %
    rs_3m:           float = 0.0
    base_depth_pct:  float = 0.0     # tightness of recent base
    vol_dryup:       bool  = False   # base volume < 50d avg
    stage2:          bool  = False
    setup_type:      str   = "NONE"
    quality_score:   float = 0.0
    # trade plan
    entry: float = 0.0; stop: float = 0.0; target1: float = 0.0; target2: float = 0.0
    rr: float = 0.0; confidence: float = 0.0
    signal_state: str = "NONE"; action: str = ""; entry_zone: str = ""
    exit_guidance: str = ""; invalidation: str = ""
    reasons: list[str] = field(default_factory=list)


def _rel_strength(stock: list[float], spy: list[float], days: int) -> float:
    if len(stock) < days + 1 or len(spy) < days + 1:
        return 0.0
    s = (stock[-1] - stock[-days-1]) / stock[-days-1] * 100 if stock[-days-1] else 0
    p = (spy[-1] - spy[-days-1]) / spy[-days-1] * 100 if spy[-days-1] else 0
    return round(s - p, 2)


def _classify(s: Swing, closes: list[float], highs: list[float],
              lows: list[float], vols: list[float]) -> tuple[str, list[str]]:
    reasons = []
    if not s.stage2:
        return "NONE", reasons

    # Recent 10-day base
    base_hi = max(highs[-10:]); base_lo = min(lows[-10:])
    base_depth = (base_hi - base_lo) / base_hi * 100 if base_hi else 100
    near_pivot = (base_hi - s.price) / s.price * 100 if s.price else 100

    # FLAT_BASE — tight multi-day consolidation near highs
    if base_depth < 8 and s.pct_from_52w_high > -10 and s.vol_dryup:
        reasons += [f"tight base {base_depth:.1f}%", "vol dry-up", f"{near_pivot:.1f}% to pivot"]
        return "FLAT_BASE", reasons

    # BREAKOUT — pushing through base high on volume
    if near_pivot < 2 and vols[-1] > (statistics.mean(vols[-50:]) * 1.3 if len(vols) >= 50 else vols[-1]):
        reasons += ["breaking base high", "volume surge"]
        return "BREAKOUT", reasons

    # PULLBACK_50MA — uptrend pulling back to rising 50SMA
    if s.sma50 and abs(s.price - s.sma50) / s.sma50 * 100 < 3 and s.price > s.sma50:
        reasons += ["pullback to 50SMA support", f"RS3m {s.rs_3m:+.0f}%"]
        return "PULLBACK_50MA", reasons

    # EARLY_STAGE2 — fresh trend, base building above 200SMA
    if s.sma200_rising and s.pct_above_52w_low > 30:
        reasons += ["early stage-2 trend", f"+{s.pct_above_52w_low:.0f}% off 52w low"]
        return "EARLY_STAGE2", reasons

    return "NONE", reasons


def _quality(s: Swing) -> float:
    if s.setup_type == "NONE":
        return 0.0
    trend = 100 if s.stage2 else 0
    rs    = max(0, min(100, 50 + s.rs_3m * 2))            # +25% RS3m = 100
    prox  = max(0, min(100, 100 + s.pct_from_52w_high * 4))  # at high=100, -25%=0
    base  = max(0, min(100, 100 - s.base_depth_pct * 6))  # tighter base scores higher
    setup_q = {"BREAKOUT":90,"FLAT_BASE":85,"PULLBACK_50MA":75,"EARLY_STAGE2":65}.get(s.setup_type,50)
    score = trend*0.25 + rs*0.25 + prox*0.15 + base*0.10 + setup_q*0.25
    return round(min(100, max(0, score)), 1)


def _build(symbol: str, bars: list, spy_closes: list[float]) -> Optional[Swing]:
    if not bars or len(bars) < 200:
        return None
    closes = [float(b.close) for b in bars]
    highs  = [float(b.high)  for b in bars]
    lows   = [float(b.low)   for b in bars]
    vols   = [float(b.volume) for b in bars]

    s = Swing(symbol=symbol)
    s.price  = closes[-1]
    s.sma50  = _sma(closes, 50)  or 0
    s.sma150 = _sma(closes, 150) or 0
    s.sma200 = _sma(closes, 200) or 0
    sma200_prev = _sma(closes[:-21], 200) if len(closes) > 221 else None
    s.sma200_rising = bool(sma200_prev and s.sma200 > sma200_prev)

    hi_52w = max(highs[-252:]) if len(highs) >= 252 else max(highs)
    lo_52w = min(lows[-252:])  if len(lows)  >= 252 else min(lows)
    s.pct_from_52w_high = round((s.price - hi_52w) / hi_52w * 100, 2) if hi_52w else 0
    s.pct_above_52w_low = round((s.price - lo_52w) / lo_52w * 100, 2) if lo_52w else 0

    s.rs_1m = _rel_strength(closes, spy_closes, 21)
    s.rs_3m = _rel_strength(closes, spy_closes, 63)

    base_hi = max(highs[-10:]); base_lo = min(lows[-10:])
    s.base_depth_pct = round((base_hi - base_lo) / base_hi * 100, 2) if base_hi else 0
    avg_vol_50 = statistics.mean(vols[-50:]) if len(vols) >= 50 else statistics.mean(vols)
    s.vol_dryup = bool(statistics.mean(vols[-5:]) < avg_vol_50)

    # Stage-2 trend template
    s.stage2 = bool(
        s.sma50 and s.sma150 and s.sma200
        and s.price > s.sma50 > s.sma150 > s.sma200
        and s.sma200_rising
        and s.pct_from_52w_high > -25
        and s.pct_above_52w_low > 30
    )

    s.setup_type, s.reasons = _classify(s, closes, highs, lows, vols)
    s.quality_score = _quality(s)

    # Trade plan — swing-sized levels
    base_hi = max(highs[-10:])
    entry = round(base_hi + 0.05, 2)                       # pivot breakout
    stop  = round(min(s.sma50, base_lo) * 0.99, 2)         # below 50SMA / base low
    risk  = max(0.01, entry - stop)
    t1    = round(entry + risk * 2.0, 2)                    # 2R
    t2    = round(entry + risk * 4.0, 2)                    # 4R measured move
    plan = build_trade_plan(
        price=s.price, entry=entry, stop=stop, target1=t1, target2=t2,
        setup_type=s.setup_type, score=s.quality_score,
        rvol=1.0, danger=0.0, horizon="swing",
    )
    s.entry, s.stop, s.target1, s.target2 = plan.entry, plan.stop, plan.target1, plan.target2
    s.rr, s.confidence = plan.rr, plan.confidence
    s.signal_state, s.action = plan.state, plan.action
    s.entry_zone, s.exit_guidance, s.invalidation = plan.entry_zone, plan.exit_guidance, plan.invalidation
    return s


def main() -> None:
    ap = argparse.ArgumentParser(description="Swing trade scanner (daily timeframe)")
    ap.add_argument("--top-n", type=int, default=25)
    ap.add_argument("--min-quality", type=float, default=55.0)
    args = ap.parse_args()

    print("=" * 60)
    print(f"SWING SCANNER  |  universe={len(DEFAULT_UNIVERSE)}  min_quality={args.min_quality}")
    print("=" * 60)

    _load_env()
    client = _client()
    universe = list(dict.fromkeys(DEFAULT_UNIVERSE))
    if "SPY" not in universe:
        universe.append("SPY")

    print(f"\nFetching 400 daily bars for {len(universe)} symbols…")
    daily = {}
    for batch in _chunked(universe, 50):
        daily.update(_fetch_daily(client, batch, days=400))

    spy_closes = [float(b.close) for b in daily.get("SPY", [])]
    if not spy_closes:
        print("WARNING: no SPY bars — relative strength will be zero")

    print("Computing trend templates…")
    cands = []
    for sym in universe:
        if sym == "SPY":
            continue
        s = _build(sym, daily.get(sym, []), spy_closes)
        if s and s.quality_score >= args.min_quality:
            cands.append(s)

    cands.sort(key=lambda c: c.quality_score, reverse=True)
    top = cands[:args.top_n]

    print(f"\n{'='*92}\nTOP {len(top)} SWING CANDIDATES\n{'='*92}")
    print(f"{'SYM':<6} {'QUAL':>4} {'SETUP':<14} {'STATE':<14} {'RS3m':>6} {'52wH':>6} "
          f"{'PRICE':>8} {'ENTRY':>8} {'STOP':>8} {'T1':>8} {'T2':>8} {'RR':>4}")
    print("-" * 110)
    for c in top:
        print(f"{c.symbol:<6} {c.quality_score:>4.0f} {c.setup_type:<14} {c.signal_state:<14} "
              f"{c.rs_3m:>+6.0f} {c.pct_from_52w_high:>+6.1f} {c.price:>8.2f} {c.entry:>8.2f} "
              f"{c.stop:>8.2f} {c.target1:>8.2f} {c.target2:>8.2f} {c.rr:>4.1f}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({
        "schema_version":  "swing_v1",
        "generated_at":    datetime.now(ET).isoformat(),
        "universe_size":   len(universe) - 1,
        "min_quality":     args.min_quality,
        "candidates":      [asdict(c) for c in top],
    }, indent=2), encoding="utf-8")
    print(f"\nWrote {OUTPUT}")


if __name__ == "__main__":
    main()
