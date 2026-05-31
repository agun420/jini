"""
Setup Backtest Engine — the keystone
====================================
Proves (or kills) a day-trading setup on HISTORY, after costs, before a dollar
is risked. Replays Alpaca minute bars over a date range, applies a precisely
defined setup, simulates realistic execution, and reports the only numbers that
matter: expectancy (R), profit factor, max drawdown — split in-sample vs
out-of-sample so you can tell edge from curve-fit.

Currently encodes ONE setup: Opening-Range Breakout (ORB) on the day's gappers.
Add more by registering a function in SETUPS.

Usage (from jini root):
    PYTHONPATH=src python3 scripts/run_setup_backtest.py --months 3
    PYTHONPATH=src python3 scripts/run_setup_backtest.py --setup orb \
        --gap-min 3 --rvol-min 1.5 --or-min 15 --r-target 2 --slippage-bps 5

Output: console report + state/backtest_<setup>.json
"""

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

JINI_ROOT = Path(__file__).resolve().parent.parent
ET        = ZoneInfo("America/New_York")
OUT_DIR   = JINI_ROOT / "state"

# Moderate-volatility universe (where intraday breakouts can actually occur).
UNIVERSE = [
    "NVDA","AMD","SMCI","COIN","MSTR","PLTR","AFRM","SOFI","UPST","RIVN","LCID",
    "MARA","RIOT","CLSK","WULF","ASTS","RKLB","ACHR","BBAI","SOUN","AI","IONQ",
    "TSLA","NFLX","META","AMZN","AVGO","ARM","MU","INTC","DELL","CRWD","NET","DDOG",
    "SNAP","PINS","RBLX","U","DKNG","CVNA","CHWY","ABNB","UBER","HOOD","SQ","SHOP",
    "BYND","GME","AMC","NIO","XPEV","LI","BABA","PDD","JD","FUBO","PLUG","FCEL",
    "ENPH","FSLR","RUN","CELH","ELF","ANF","CVNA","W","CART","RDDT","ARM","TSM",
]


# ── Env / client ───────────────────────────────────────────────────────────
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


def _fetch_daily(client, symbols, start, end):
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    req = StockBarsRequest(symbol_or_symbols=symbols, timeframe=TimeFrame.Day,
                           start=start, end=end, feed=_feed())
    try:
        return {s: list(client.get_stock_bars(req).data.get(s, [])) for s in symbols}
    except Exception as e:
        print(f"  daily fetch error: {e}")
        return {}


def _fetch_minute(client, symbol, start, end):
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Minute,
                           start=start, end=end, feed=_feed())
    try:
        return list(client.get_stock_bars(req).data.get(symbol, []))
    except Exception as e:
        print(f"  minute fetch error {symbol}: {e}")
        return []


# ── Trade record ───────────────────────────────────────────────────────────
@dataclass
class Trade:
    date:    str
    symbol:  str
    setup:   str
    side:    str           # long / short
    entry:   float
    stop:    float
    target:  float
    exit:    float
    exit_reason: str       # TARGET / STOP / EOD
    r_multiple:  float
    gap_pct:     float
    rvol:        float


# ── Cost model ─────────────────────────────────────────────────────────────
def _apply_slippage(price: float, bps: float, side: str) -> float:
    """side='buy' pays up, 'sell' receives less."""
    adj = price * bps / 10000.0
    return price + adj if side == "buy" else price - adj


# ── Setup: Opening-Range Breakout ──────────────────────────────────────────
def setup_orb(day_bars, prev_close, day_vol_avg, cfg) -> dict | None:
    """
    day_bars: list of this day's minute bars (ET regular session), ascending.
    Returns a trade spec dict or None if the day doesn't qualify / no trigger.
    """
    if len(day_bars) < cfg["or_min"] + 5:
        return None

    session_open = float(day_bars[0].open)
    gap_pct = (session_open - prev_close) / prev_close * 100 if prev_close else 0.0
    if gap_pct < cfg["gap_min"]:
        return None
    if not (cfg["price_min"] <= session_open <= cfg["price_max"]):
        return None

    # RVOL proxy: first-30-min volume annualized vs avg daily volume
    first30 = sum(float(b.volume) for b in day_bars[:30])
    rvol = (first30 * 13) / day_vol_avg if day_vol_avg else 0.0  # ~13 half-hours/session
    if rvol < cfg["rvol_min"]:
        return None

    # Opening range = first or_min bars
    orb = day_bars[:cfg["or_min"]]
    or_high = max(float(b.high) for b in orb)
    or_low  = min(float(b.low)  for b in orb)

    # Look for the first bar after the OR that breaks above or_high
    for i in range(cfg["or_min"], len(day_bars)):
        b = day_bars[i]
        if float(b.high) >= or_high:
            entry = _apply_slippage(or_high, cfg["slippage_bps"], "buy")
            stop  = or_low
            if entry <= stop:
                return None
            target = entry + (entry - stop) * cfg["r_target"]
            return {"side": "long", "entry": entry, "stop": stop, "target": target,
                    "trigger_idx": i, "or_high": or_high, "or_low": or_low,
                    "gap_pct": round(gap_pct, 2), "rvol": round(rvol, 2)}
    return None


def setup_orb_fade(day_bars, prev_close, day_vol_avg, cfg) -> dict | None:
    """
    Gap-FADE (short): same gapper universe, but trade the FAILED breakout.
    After the opening range, short the first break BELOW the OR low — capturing
    the fade-to-EOD pattern that killed the long ORB. Stop above OR high.
    """
    if len(day_bars) < cfg["or_min"] + 5:
        return None
    session_open = float(day_bars[0].open)
    gap_pct = (session_open - prev_close) / prev_close * 100 if prev_close else 0.0
    if gap_pct < cfg["gap_min"]:
        return None
    if not (cfg["price_min"] <= session_open <= cfg["price_max"]):
        return None
    first30 = sum(float(b.volume) for b in day_bars[:30])
    rvol = (first30 * 13) / day_vol_avg if day_vol_avg else 0.0
    if rvol < cfg["rvol_min"]:
        return None

    orb = day_bars[:cfg["or_min"]]
    or_high = max(float(b.high) for b in orb)
    or_low  = min(float(b.low)  for b in orb)

    for i in range(cfg["or_min"], len(day_bars)):
        b = day_bars[i]
        if float(b.low) <= or_low:                      # breakdown → short
            entry = _apply_slippage(or_low, cfg["slippage_bps"], "sell")
            stop  = or_high
            if stop <= entry:
                return None
            risk = stop - entry
            target = entry - risk * cfg["r_target"]
            return {"side": "short", "entry": entry, "stop": stop, "target": target,
                    "trigger_idx": i, "or_high": or_high, "or_low": or_low,
                    "gap_pct": round(gap_pct, 2), "rvol": round(rvol, 2)}
    return None


SETUPS = {"orb": setup_orb, "orb_fade": setup_orb_fade}


# ── Execution simulator ────────────────────────────────────────────────────
def _simulate(day_bars, spec, cfg) -> tuple[float, str, float]:
    """
    Walk bars from trigger forward. Conservative path-dependence: if a single
    bar's range straddles BOTH stop and target, assume STOP hit first.
    Handles long and short. Returns (exit_price, reason, r_multiple).
    """
    side = spec.get("side", "long")
    entry, stop, target = spec["entry"], spec["stop"], spec["target"]

    if side == "long":
        risk = entry - stop
        for j in range(spec["trigger_idx"], len(day_bars)):
            b = day_bars[j]
            if float(b.low) <= stop:                 # stop wins ties
                ex = _apply_slippage(stop, cfg["slippage_bps"], "sell")
                return ex, "STOP", (ex - entry) / risk
            if float(b.high) >= target:
                ex = _apply_slippage(target, cfg["slippage_bps"], "sell")
                return ex, "TARGET", (ex - entry) / risk
        ex = _apply_slippage(float(day_bars[-1].close), cfg["slippage_bps"], "sell")
        return ex, "EOD", (ex - entry) / risk

    # short
    risk = stop - entry
    for j in range(spec["trigger_idx"], len(day_bars)):
        b = day_bars[j]
        if float(b.high) >= stop:                    # stop (price rises) wins ties
            ex = _apply_slippage(stop, cfg["slippage_bps"], "buy")
            return ex, "STOP", (entry - ex) / risk
        if float(b.low) <= target:                   # target (price falls)
            ex = _apply_slippage(target, cfg["slippage_bps"], "buy")
            return ex, "TARGET", (entry - ex) / risk
    ex = _apply_slippage(float(day_bars[-1].close), cfg["slippage_bps"], "buy")
    return ex, "EOD", (entry - ex) / risk


# ── Day grouping ───────────────────────────────────────────────────────────
def _group_by_session(bars):
    """Group minute bars into {date: [regular-session bars]} in ET (09:30–16:00)."""
    days = defaultdict(list)
    for b in bars:
        t = b.timestamp.astimezone(ET)
        mins = t.hour * 60 + t.minute
        if 570 <= mins < 960:  # 09:30–16:00
            days[t.date().isoformat()].append(b)
    for d in days:
        days[d].sort(key=lambda x: x.timestamp)
    return days


# ── Metrics ────────────────────────────────────────────────────────────────
def _metrics(trades: list[Trade]) -> dict:
    if not trades:
        return {"trades": 0}
    rs = [t.r_multiple for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    # Equity curve in R + max drawdown
    eq, peak, mdd = 0.0, 0.0, 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    exp = statistics.mean(rs)
    return {
        "trades":        len(trades),
        "win_rate":      round(len(wins) / len(rs), 3),
        "expectancy_R":  round(exp, 3),
        "total_R":       round(sum(rs), 2),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
        "avg_win_R":     round(statistics.mean(wins), 3) if wins else 0,
        "avg_loss_R":    round(statistics.mean(losses), 3) if losses else 0,
        "max_drawdown_R":round(mdd, 2),
        "best_R":        round(max(rs), 2),
        "worst_R":       round(min(rs), 2),
        "exit_mix":      dict(_count(t.exit_reason for t in trades)),
    }


def _count(it):
    c = defaultdict(int)
    for x in it:
        c[x] += 1
    return c


def _verdict(m_oos: dict) -> list[str]:
    out = []
    n = m_oos.get("trades", 0)
    if n < 30:
        out.append(f"SAMPLE: only {n} out-of-sample trades — directional, not conclusive. Widen --months or loosen filters.")
    exp = m_oos.get("expectancy_R")
    pf  = m_oos.get("profit_factor")
    if exp is None:
        return out + ["No out-of-sample trades to judge."]
    if exp > 0.15 and (pf or 0) > 1.3:
        out.append(f"EDGE (out-of-sample): +{exp}R/trade, profit factor {pf}. This setup is worth paper-trading live. Forward-test before real size.")
    elif exp > 0:
        out.append(f"MARGINAL: +{exp}R out-of-sample but profit factor {pf}. Thin — costs/slippage could erase it. Tighten entry filters before trusting.")
    else:
        out.append(f"NO EDGE: {exp}R out-of-sample. This setup does not survive costs. Do NOT trade it — change the setup, not the parameters.")
    out.append("Reminder: expectancy here assumes STOP-first on ambiguous bars (conservative). Live results trend toward this, not the optimistic case.")
    return out


# ── Main ───────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="Day-trading setup backtest engine")
    ap.add_argument("--setup", default="orb", choices=list(SETUPS))
    ap.add_argument("--months", type=int, default=3, help="History window (months)")
    ap.add_argument("--gap-min", type=float, default=3.0, help="Min gap %% to qualify")
    ap.add_argument("--rvol-min", type=float, default=1.3, help="Min relative volume")
    ap.add_argument("--price-min", type=float, default=2.0)
    ap.add_argument("--price-max", type=float, default=100.0)
    ap.add_argument("--or-min", type=int, default=15, help="Opening-range minutes")
    ap.add_argument("--r-target", type=float, default=2.0, help="Target in R multiples")
    ap.add_argument("--slippage-bps", type=float, default=5.0, help="Slippage per side (bps)")
    ap.add_argument("--oos-frac", type=float, default=0.3, help="Out-of-sample tail fraction")
    args = ap.parse_args()

    cfg = {"gap_min": args.gap_min, "rvol_min": args.rvol_min,
           "price_min": args.price_min, "price_max": args.price_max,
           "or_min": args.or_min, "r_target": args.r_target,
           "slippage_bps": args.slippage_bps}
    setup_fn = SETUPS[args.setup]

    print("=" * 72)
    print(f"BACKTEST  setup={args.setup}  {args.months}mo  gap≥{args.gap_min}%  "
          f"rvol≥{args.rvol_min}  OR={args.or_min}m  target={args.r_target}R  "
          f"slip={args.slippage_bps}bps")
    print("=" * 72)

    _load_env()
    client = _client()
    end   = datetime.now(timezone.utc)
    start = end - timedelta(days=args.months * 31 + 30)  # pad for daily baseline

    print(f"\nFetching daily baselines for {len(UNIVERSE)} symbols…")
    daily = _fetch_daily(client, list(dict.fromkeys(UNIVERSE)), start, end)

    all_trades: list[Trade] = []
    syms = list(dict.fromkeys(UNIVERSE))
    for n, sym in enumerate(syms, 1):
        dbars = daily.get(sym, [])
        if len(dbars) < 25:
            continue
        # prev_close and 20d avg vol keyed by date
        prev_close_by_date, volavg_by_date = {}, {}
        closes = [float(b.close) for b in dbars]
        vols   = [float(b.volume) for b in dbars]
        for i in range(1, len(dbars)):
            d = dbars[i].timestamp.astimezone(ET).date().isoformat()
            prev_close_by_date[d] = closes[i-1]
            lo = max(0, i-20)
            volavg_by_date[d] = statistics.mean(vols[lo:i]) if i > lo else vols[i-1]

        minute = _fetch_minute(client, sym, start, end)
        if not minute:
            continue
        sessions = _group_by_session(minute)
        for date, day_bars in sessions.items():
            pc = prev_close_by_date.get(date)
            va = volavg_by_date.get(date)
            if pc is None or va is None:
                continue
            spec = setup_fn(day_bars, pc, va, cfg)
            if not spec:
                continue
            ex, reason, r = _simulate(day_bars, spec, cfg)
            all_trades.append(Trade(
                date=date, symbol=sym, setup=args.setup, side=spec.get("side","long"),
                entry=round(spec["entry"],2), stop=round(spec["stop"],2),
                target=round(spec["target"],2), exit=round(ex,2),
                exit_reason=reason, r_multiple=round(r,3),
                gap_pct=spec["gap_pct"], rvol=spec["rvol"]))
        if n % 20 == 0:
            print(f"  …processed {n}/{len(syms)} symbols, {len(all_trades)} trades so far")

    if not all_trades:
        print("\nNo qualifying trades in the window. Loosen --gap-min / --rvol-min or widen --months.")
        return

    all_trades.sort(key=lambda t: t.date)
    split = int(len(all_trades) * (1 - args.oos_frac))
    in_sample  = all_trades[:split]
    out_sample = all_trades[split:]

    m_all = _metrics(all_trades)
    m_is  = _metrics(in_sample)
    m_oos = _metrics(out_sample)

    def show(title, m):
        print(f"\n── {title} ──")
        for k, v in m.items():
            print(f"   {k:<16} {v}")

    show(f"ALL ({len(all_trades)} trades)", m_all)
    show(f"IN-SAMPLE (first {len(in_sample)})", m_is)
    show(f"OUT-OF-SAMPLE (last {len(out_sample)})", m_oos)

    print("\n── Sample winners/losers ──")
    for t in sorted(all_trades, key=lambda x: -x.r_multiple)[:3]:
        print(f"   +{t.r_multiple:>5.2f}R  {t.symbol:<6} {t.date}  gap={t.gap_pct}% {t.exit_reason}")
    for t in sorted(all_trades, key=lambda x: x.r_multiple)[:3]:
        print(f"   {t.r_multiple:>6.2f}R  {t.symbol:<6} {t.date}  gap={t.gap_pct}% {t.exit_reason}")

    print("\n" + "=" * 72)
    print("VERDICT")
    print("=" * 72)
    for i, line in enumerate(_verdict(m_oos), 1):
        print(f"  {i}. {line}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"backtest_{args.setup}.json"
    out_path.write_text(json.dumps({
        "generated_at": datetime.now(ET).isoformat(),
        "config": vars(args),
        "metrics_all": m_all, "metrics_in_sample": m_is, "metrics_out_of_sample": m_oos,
        "verdict": _verdict(m_oos),
        "trades": [asdict(t) for t in all_trades],
    }, indent=2), encoding="utf-8")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
