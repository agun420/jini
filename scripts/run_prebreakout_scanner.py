"""
Pre-Breakout Scanner
====================
Predictive scanner that ranks stocks by **explosion probability** — the
likelihood the stock will move >2% in the next 30 minutes — using
LEADING indicators rather than lagging ones.

Predictive features (these LEAD price moves):
  - Volatility compression  (ATR contracting, Bollinger band squeeze)
  - Volume accumulation     (OBV rising while price flat/declining)
  - Relative strength       (outperforming SPY before the move)
  - Inside-bar count        (tight consolidation)
  - VWAP slope              (positive slope = institutional buying)
  - Pre-market positioning  (gap + RVOL before 9:30)
  - Setup classification    (GAP_GO / ORB / VWAP_RECLAIM / COIL / FLAG)

Output: state/prebreakout_candidates.json (top 20 ranked candidates with
explosion_probability + setup_type + entry/stop/target levels).

Usage:
    PYTHONPATH=src python3 scripts/run_prebreakout_scanner.py
    PYTHONPATH=src python3 scripts/run_prebreakout_scanner.py --universe-size 200
"""

import argparse
import json
import os
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

JINI_ROOT  = Path(__file__).resolve().parent.parent
ET         = ZoneInfo("America/New_York")
OUTPUT     = JINI_ROOT / "state" / "prebreakout_candidates.json"

# Ensure src/ is importable even without PYTHONPATH=src
sys.path.insert(0, str(JINI_ROOT / "src"))
from prediction_engine.trade_plan import build_trade_plan  # noqa: E402

# ── Universe seed: liquid daily movers we want to monitor ─────────────────
DEFAULT_UNIVERSE = [
    # Mega-cap tech
    "NVDA", "AAPL", "MSFT", "META", "GOOGL", "AMZN", "TSLA", "AVGO", "AMD",
    "NFLX", "ADBE", "CRM", "ORCL", "INTC", "QCOM", "MU", "TSM", "ARM",
    # AI / data / cloud
    "PLTR", "SMCI", "AI", "C3AI", "PATH", "SNOW", "DDOG", "MDB", "NET", "S",
    "ESTC", "ZS", "CRWD", "OKTA", "FTNT", "PANW", "NOW", "ANET",
    # High-beta / momentum
    "COIN", "MSTR", "RIVN", "LCID", "F", "GM", "NIO", "XPEV", "LI", "BYND",
    "AFRM", "SOFI", "UPST", "HOOD", "RKLB", "ASTS", "ACHR", "JOBY", "BLDE",
    # Biotech volatility
    "MRNA", "NVAX", "BNTX", "VRTX", "REGN", "BMY", "GILD", "PFE", "ABBV",
    # Energy / crypto adjacent
    "RIOT", "MARA", "CLSK", "WULF", "BTBT", "HUT", "BITF", "HIVE",
    # ETFs (for relative strength baseline)
    "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "ARKK", "XBI",
    # Meme / retail favorites
    "GME", "AMC", "BBBY", "DJT", "CVNA", "BBAI", "SOUN", "OPEN",
    # Industrials / cyclicals
    "BA", "CAT", "DE", "GE", "HD", "LOW", "WMT", "COST", "TGT", "MCD",
    # Travel
    "DAL", "UAL", "AAL", "LUV", "CCL", "RCL", "NCLH", "MAR", "ABNB", "BKNG",
    # Other liquid names
    "DIS", "NKE", "SBUX", "CMG", "DKNG", "PENN", "DKNG", "ROKU", "PINS",
    "PYPL", "SQ", "SHOP", "ABNB", "UBER", "LYFT", "DASH",
]


# ═══════════════════════════════════════════════════════════════════════════
# Env / Alpaca client
# ═══════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════
# Data fetching
# ═══════════════════════════════════════════════════════════════════════════

def _fetch_intraday_bars(client, symbols: list[str], minutes_back: int = 90) -> dict:
    """Fetch 1-minute bars for many symbols in one call."""
    from alpaca.data.requests  import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    now   = datetime.now(timezone.utc)
    start = now - timedelta(minutes=minutes_back)
    req = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Minute,
        start=start,
        end=now,
        feed=_feed(),
    )
    try:
        resp = client.get_stock_bars(req)
        return {s: list(resp.data.get(s, [])) for s in symbols}
    except Exception as e:
        print(f"  intraday fetch error: {e}")
        return {}


def _fetch_daily_bars(client, symbols: list[str], days_back: int = 30) -> dict:
    from alpaca.data.requests  import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    now   = datetime.now(timezone.utc)
    start = now - timedelta(days=days_back)
    req = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start,
        end=now,
        feed=_feed(),
    )
    try:
        resp = client.get_stock_bars(req)
        return {s: list(resp.data.get(s, [])) for s in symbols}
    except Exception as e:
        print(f"  daily fetch error: {e}")
        return {}


def _chunked(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


# ═══════════════════════════════════════════════════════════════════════════
# Feature computation
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Features:
    symbol:           str
    price:            float = 0.0
    # Predictive
    atr_compression:  float = 0.0   # 0-100: how much ATR has shrunk vs 20d avg
    obv_slope:        float = 0.0   # accumulation pressure (-1..1)
    rel_strength:     float = 0.0   # vs SPY in last 15 min, %
    vwap:             float = 0.0
    vwap_slope:       float = 0.0   # positive = institutional buying
    inside_bar_count: int   = 0     # consecutive inside bars
    bb_squeeze:       bool  = False # Bollinger width < 20% of 20d max
    coil_score:       float = 0.0   # composite compression score 0-100
    # Reactive context
    day_change_pct:   float = 0.0
    rvol:             float = 1.0
    distance_hod_pct: float = 0.0
    distance_vwap:    float = 0.0
    # Setup
    setup_type:       str   = "NONE"
    explosion_prob:   float = 0.0
    # Trade plan (filled by prediction_engine.trade_plan)
    entry:            float = 0.0
    stop:             float = 0.0
    target1:          float = 0.0
    target2:          float = 0.0
    rr:               float = 0.0
    confidence:       float = 0.0
    signal_state:     str   = "NONE"   # POTENTIAL/WATCH/TRIGGER_READY/ACTIVE/EXTENDED/...
    action:           str   = ""       # plain-English what-to-do-now
    entry_zone:       str   = ""       # ENTER NOW / WAIT / DONE
    exit_guidance:    str   = ""       # when/how to sell
    invalidation:     str   = ""
    reasons:          list[str] = field(default_factory=list)


def _atr(bars: list, period: int = 14) -> float:
    if len(bars) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = float(bars[i].high), float(bars[i].low), float(bars[i-1].close)
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return statistics.mean(trs[-period:])


def _obv_slope(bars: list, lookback: int = 30) -> float:
    """OBV slope normalized to -1..1 (positive = accumulation)."""
    if len(bars) < lookback + 1:
        return 0.0
    obv = 0.0
    obv_series = [0.0]
    for i in range(1, len(bars)):
        if bars[i].close > bars[i-1].close:
            obv += float(bars[i].volume)
        elif bars[i].close < bars[i-1].close:
            obv -= float(bars[i].volume)
        obv_series.append(obv)
    window = obv_series[-lookback:]
    if max(window) - min(window) == 0:
        return 0.0
    slope = (window[-1] - window[0]) / (max(abs(min(window)), abs(max(window))) + 1)
    return max(-1.0, min(1.0, slope))


def _vwap(bars: list) -> tuple[float, float]:
    """Returns (current VWAP, slope of last 10 bars)."""
    if len(bars) < 5:
        return 0.0, 0.0
    cum_pv = 0.0
    cum_v  = 0.0
    series = []
    for b in bars:
        tp = (float(b.high) + float(b.low) + float(b.close)) / 3
        cum_pv += tp * float(b.volume)
        cum_v  += float(b.volume)
        series.append(cum_pv / cum_v if cum_v > 0 else float(b.close))
    if len(series) < 10:
        return series[-1], 0.0
    return series[-1], (series[-1] - series[-10]) / series[-10] * 100


def _bollinger_squeeze(bars: list, period: int = 20) -> tuple[bool, float]:
    """Returns (is_squeezing, current_width_pct)."""
    if len(bars) < period * 2:
        return False, 0.0
    closes = [float(b.close) for b in bars]
    widths = []
    for i in range(period, len(closes) + 1):
        window = closes[i-period:i]
        mean = statistics.mean(window)
        std  = statistics.pstdev(window)
        width = (4 * std) / mean if mean else 0
        widths.append(width)
    if not widths:
        return False, 0.0
    current = widths[-1]
    max_recent = max(widths[-period:]) if len(widths) >= period else max(widths)
    is_squeezing = (current / max_recent) < 0.5 if max_recent > 0 else False
    return is_squeezing, current * 100


def _inside_bar_count(bars: list) -> int:
    """Count consecutive inside bars from the right."""
    if len(bars) < 2:
        return 0
    count = 0
    for i in range(len(bars) - 1, 0, -1):
        if float(bars[i].high) <= float(bars[i-1].high) and float(bars[i].low) >= float(bars[i-1].low):
            count += 1
        else:
            break
    return count


def _atr_compression(intraday: list, daily: list) -> float:
    """0-100 — how compressed is current ATR vs 20-day average?"""
    if len(intraday) < 15 or len(daily) < 10:
        return 0.0
    intra_atr = _atr(intraday, 14)
    daily_atrs = []
    for i in range(1, len(daily)):
        tr = max(
            float(daily[i].high) - float(daily[i].low),
            abs(float(daily[i].high) - float(daily[i-1].close)),
            abs(float(daily[i].low)  - float(daily[i-1].close)),
        )
        daily_atrs.append(tr)
    avg_daily_atr = statistics.mean(daily_atrs) if daily_atrs else 0
    if avg_daily_atr == 0:
        return 0.0
    # Today's accumulated intraday range vs avg daily range
    if not intraday:
        return 0.0
    day_hi = max(float(b.high) for b in intraday)
    day_lo = min(float(b.low)  for b in intraday)
    today_range = day_hi - day_lo
    ratio = today_range / avg_daily_atr
    # Less than 50% of average daily range = highly compressed = high score
    if ratio < 0.3:
        return 95.0
    if ratio < 0.5:
        return 80.0
    if ratio < 0.7:
        return 60.0
    if ratio < 0.9:
        return 40.0
    return 20.0


def _relative_strength(stock_bars: list, spy_bars: list, lookback: int = 15) -> float:
    """% outperformance of stock vs SPY in last `lookback` minutes."""
    if len(stock_bars) < lookback or len(spy_bars) < lookback:
        return 0.0
    s_start = float(stock_bars[-lookback].close)
    s_end   = float(stock_bars[-1].close)
    p_start = float(spy_bars[-lookback].close)
    p_end   = float(spy_bars[-1].close)
    if s_start == 0 or p_start == 0:
        return 0.0
    s_pct = (s_end - s_start) / s_start * 100
    p_pct = (p_end - p_start) / p_start * 100
    return round(s_pct - p_pct, 3)


def _rvol(intraday: list, daily: list) -> float:
    """Today's volume so far / average daily volume * (fraction of day elapsed)."""
    if not intraday or len(daily) < 5:
        return 1.0
    today_vol = sum(float(b.volume) for b in intraday)
    avg_daily_vol = statistics.mean(float(b.volume) for b in daily[-10:])
    if avg_daily_vol == 0:
        return 1.0
    now_et = datetime.now(ET)
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    minutes_elapsed = max(1, (now_et - market_open).total_seconds() / 60)
    fraction_of_day = min(1.0, minutes_elapsed / 390)
    expected_vol = avg_daily_vol * fraction_of_day
    return round(today_vol / expected_vol, 2) if expected_vol > 0 else 1.0


# ═══════════════════════════════════════════════════════════════════════════
# Setup classification + explosion probability
# ═══════════════════════════════════════════════════════════════════════════

def _classify_setup(f: Features) -> tuple[str, list[str]]:
    """Identify the highest-quality setup forming on this stock."""
    reasons = []
    now_et = datetime.now(ET)
    is_premarket = now_et.hour < 9 or (now_et.hour == 9 and now_et.minute < 30)
    is_opening   = now_et.hour == 9 and 30 <= now_et.minute <= 45
    is_powerhour = now_et.hour >= 15

    # COIL_BREAKOUT — tight consolidation about to expand
    if f.coil_score >= 70 and f.inside_bar_count >= 3 and f.obv_slope > 0.2:
        reasons.append(f"coil={f.coil_score:.0f}")
        reasons.append(f"inside_bars={f.inside_bar_count}")
        reasons.append(f"obv_slope={f.obv_slope:.2f}")
        return "COIL_BREAKOUT", reasons

    # GAP_GO — pre-market gap with continuation
    if is_premarket or (is_opening and f.day_change_pct >= 3 and f.rvol >= 2):
        if f.day_change_pct >= 3 and f.rvol >= 2:
            reasons.append(f"gap={f.day_change_pct:.1f}%")
            reasons.append(f"rvol={f.rvol:.1f}x")
            return "GAP_GO", reasons

    # ORB_LONG — opening range breakout
    if is_opening and f.day_change_pct > 0 and f.distance_hod_pct < 0.3 and f.rvol >= 1.5:
        reasons.append(f"opening_strength={f.day_change_pct:.1f}%")
        reasons.append(f"near_hod={f.distance_hod_pct:.2f}%")
        reasons.append(f"rvol={f.rvol:.1f}x")
        return "ORB_LONG", reasons

    # VWAP_RECLAIM — was below VWAP, now above with rising volume
    if -0.3 < f.distance_vwap < 0.5 and f.vwap_slope > 0 and f.obv_slope > 0.1:
        reasons.append(f"vwap_reclaim (slope={f.vwap_slope:.2f})")
        reasons.append(f"accum (obv={f.obv_slope:.2f})")
        return "VWAP_RECLAIM", reasons

    # LATE_DAY_MOMO — 3pm+ rising on volume
    if is_powerhour and f.day_change_pct > 1 and f.rel_strength > 0.3 and f.rvol >= 1.3:
        reasons.append(f"power_hour rs={f.rel_strength:.2f}%")
        reasons.append(f"rvol={f.rvol:.1f}x")
        return "LATE_DAY_MOMO", reasons

    # BULL_FLAG — pullback in uptrend with declining volume
    if f.day_change_pct > 2 and f.distance_hod_pct > 0.5 and f.distance_hod_pct < 2.0 \
            and f.obv_slope > 0 and f.bb_squeeze:
        reasons.append(f"flag_pullback (-{f.distance_hod_pct:.2f}% from HOD)")
        reasons.append("bb_squeeze")
        return "BULL_FLAG", reasons

    return "NONE", reasons


def _explosion_probability(f: Features) -> float:
    """Composite 0-100 probability stock will move >2% in next 30 min."""
    if f.setup_type == "NONE":
        return 0.0

    # Component scores
    coil      = f.coil_score                                  # 0-100
    accum     = max(0, f.obv_slope) * 100                     # 0-100
    rs        = max(0, min(100, 50 + f.rel_strength * 25))    # centered at 0% = 50
    vwap_pres = max(0, min(100, 50 + f.vwap_slope * 50))      # positive slope helps
    volume    = max(0, min(100, (f.rvol - 1) * 50))           # rvol 3x = 100
    setup_q   = {
        "COIL_BREAKOUT": 90, "GAP_GO": 85, "ORB_LONG": 80,
        "VWAP_RECLAIM":  70, "BULL_FLAG": 75, "LATE_DAY_MOMO": 65,
        "NONE": 0,
    }.get(f.setup_type, 50)

    # Weighted blend — predictive features get more weight
    score = (
        coil      * 0.20 +
        accum     * 0.20 +
        rs        * 0.15 +
        vwap_pres * 0.10 +
        volume    * 0.10 +
        setup_q   * 0.25
    )
    return round(min(100, max(0, score)), 2)


def _entry_stop_target(f: Features, intraday: list) -> tuple[float, float, float]:
    """Conservative entry/stop/target based on setup type."""
    if not intraday:
        return 0.0, 0.0, 0.0
    last_close = float(intraday[-1].close)
    day_hi = max(float(b.high) for b in intraday)
    day_lo = min(float(b.low)  for b in intraday)
    intra_atr = _atr(intraday, 14)

    if f.setup_type == "COIL_BREAKOUT":
        entry  = day_hi + 0.05
        stop   = day_lo - 0.05
        target = entry + (entry - stop) * 2  # 2R
    elif f.setup_type == "GAP_GO":
        entry  = last_close + 0.05
        stop   = last_close - intra_atr * 1.5
        target = entry + intra_atr * 3
    elif f.setup_type == "ORB_LONG":
        entry  = day_hi + 0.05
        stop   = max(day_lo, f.vwap)
        target = entry + (entry - stop) * 2
    elif f.setup_type == "VWAP_RECLAIM":
        entry  = max(last_close, f.vwap) + 0.05
        stop   = f.vwap - intra_atr * 0.5
        target = entry + (entry - stop) * 2
    elif f.setup_type == "BULL_FLAG":
        entry  = day_hi + 0.05
        stop   = last_close - intra_atr
        target = entry + (day_hi - day_lo)
    elif f.setup_type == "LATE_DAY_MOMO":
        entry  = last_close + 0.05
        stop   = last_close - intra_atr * 1.2
        target = entry + intra_atr * 2
    else:
        return 0.0, 0.0, 0.0

    return round(entry, 2), round(stop, 2), round(target, 2)


# ═══════════════════════════════════════════════════════════════════════════
# Per-symbol pipeline
# ═══════════════════════════════════════════════════════════════════════════

def _build_features(symbol: str, intraday: list, daily: list, spy_intraday: list) -> Optional[Features]:
    if not intraday or len(intraday) < 15 or not daily or len(daily) < 10:
        return None

    f = Features(symbol=symbol)
    f.price            = float(intraday[-1].close)
    f.atr_compression  = _atr_compression(intraday, daily)
    f.obv_slope        = _obv_slope(intraday)
    f.rel_strength     = _relative_strength(intraday, spy_intraday)
    f.vwap, f.vwap_slope = _vwap(intraday)
    f.inside_bar_count = _inside_bar_count(intraday[-10:])
    is_squeeze, _      = _bollinger_squeeze(intraday)
    f.bb_squeeze       = is_squeeze
    f.coil_score       = round(
        f.atr_compression * 0.5 +
        (50 if is_squeeze else 0) * 0.3 +
        min(100, f.inside_bar_count * 20) * 0.2,
        2,
    )
    # Reactive context
    prev_close = float(daily[-2].close) if len(daily) >= 2 else f.price
    f.day_change_pct  = round((f.price - prev_close) / prev_close * 100, 3) if prev_close else 0
    f.rvol            = _rvol(intraday, daily)
    day_hi            = max(float(b.high) for b in intraday)
    f.distance_hod_pct = round((day_hi - f.price) / f.price * 100, 3) if f.price else 0
    f.distance_vwap   = round((f.price - f.vwap) / f.vwap * 100, 3) if f.vwap else 0

    # Setup + score
    f.setup_type, f.reasons = _classify_setup(f)
    f.explosion_prob        = _explosion_probability(f)

    # Setup-specific raw levels → full trade plan (entry/stop/T1/T2/state/action)
    raw_entry, raw_stop, raw_t2 = _entry_stop_target(f, intraday)
    intra_atr = _atr(intraday, 14)
    plan = build_trade_plan(
        price=f.price, entry=raw_entry, stop=raw_stop, target2=raw_t2,
        vwap=f.vwap, atr=intra_atr, day_high=day_hi,
        setup_type=f.setup_type, score=f.explosion_prob,
        rvol=f.rvol, danger=0.0,
    )
    f.entry         = plan.entry
    f.stop          = plan.stop
    f.target1       = plan.target1
    f.target2       = plan.target2
    f.rr            = plan.rr
    f.confidence    = plan.confidence
    f.signal_state  = plan.state
    f.action        = plan.action
    f.entry_zone    = plan.entry_zone
    f.exit_guidance = plan.exit_guidance
    f.invalidation  = plan.invalidation
    return f


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-breakout predictive scanner")
    parser.add_argument("--universe-size", type=int, default=len(DEFAULT_UNIVERSE))
    parser.add_argument("--top-n",         type=int, default=20)
    parser.add_argument("--min-prob",      type=float, default=55.0,
                        help="Min explosion_probability to include")
    args = parser.parse_args()

    print("=" * 60)
    print(f"PRE-BREAKOUT SCANNER  |  universe={args.universe_size}  top={args.top_n}")
    print(f"market_open={_market_is_open()}  feed={_feed()}")
    print("=" * 60)

    _load_env()
    client = _alpaca_client()

    universe = DEFAULT_UNIVERSE[:args.universe_size]
    if "SPY" not in universe:
        universe.append("SPY")

    # Batch fetch in groups of 50 to stay under URL limits
    print(f"\nFetching intraday + daily bars for {len(universe)} symbols…")
    intraday_all: dict[str, list] = {}
    daily_all:    dict[str, list] = {}
    for batch in _chunked(universe, 50):
        intraday_all.update(_fetch_intraday_bars(client, batch, minutes_back=120))
        daily_all.update(_fetch_daily_bars(client, batch, days_back=30))

    spy_intraday = intraday_all.get("SPY", [])
    if not spy_intraday:
        print("WARNING: no SPY bars — relative strength will be zero")

    print("Computing features…")
    candidates: list[Features] = []
    for sym in universe:
        if sym == "SPY":
            continue
        f = _build_features(sym, intraday_all.get(sym, []), daily_all.get(sym, []), spy_intraday)
        if f and f.explosion_prob >= args.min_prob:
            candidates.append(f)

    candidates.sort(key=lambda c: c.explosion_prob, reverse=True)
    top = candidates[:args.top_n]

    print(f"\n{'='*108}\nTOP {len(top)} PRE-BREAKOUT CANDIDATES\n{'='*108}")
    print(f"{'SYM':<6} {'PROB':>5} {'SETUP':<14} {'STATE':<14} "
          f"{'PRICE':>7} {'ENTRY':>7} {'SL':>7} {'T1':>7} {'T2':>7} {'R/R':>5} {'CONF':>5}")
    print("-" * 108)
    for c in top:
        print(
            f"{c.symbol:<6} {c.explosion_prob:>5.1f} {c.setup_type:<14} {c.signal_state:<14} "
            f"{c.price:>7.2f} {c.entry:>7.2f} {c.stop:>7.2f} {c.target1:>7.2f} "
            f"{c.target2:>7.2f} {c.rr:>4.1f}R {c.confidence:>4.0f}%"
        )
        print(f"       → {c.action}")

    # ── Write structured output ──────────────────────────────────────────
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version":  "prebreakout_v1",
        "generated_at":    datetime.now(ET).isoformat(),
        "market_open":     _market_is_open(),
        "universe_size":   len(universe) - 1,
        "min_probability": args.min_prob,
        "candidates":      [asdict(c) for c in top],
    }
    OUTPUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWrote {OUTPUT}")


def _market_is_open() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    return now.replace(hour=9, minute=30, second=0, microsecond=0) <= now <= \
           now.replace(hour=16, minute=0, second=0, microsecond=0)


if __name__ == "__main__":
    main()
