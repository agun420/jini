from __future__ import annotations
import json, os, statistics, logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from prediction_engine.scanners.alpaca_paid_config import get_paid_settings, get_universe

OUTPUT_PATH = Path("state/prediction_engine/dynamic_alpaca_candidates.json")
DOCS_OUTPUT_PATH = Path("docs/data/prediction_engine/alpaca_paid_market_candidates.json")
HEALTH_PATH = Path("docs/data/prediction_engine/alpaca_market_scanner_health.json")

def now_utc(): return datetime.now(timezone.utc)
def now_utc_iso(): return now_utc().isoformat()
def safe_float(v, default=None):
    try:
        if v is None or v == "": return default
        return float(v)
    except Exception: return default

def write_json(path: Path, payload: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")

def headers():
    key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
    secret = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
    if not key or not secret: raise RuntimeError("Missing Alpaca API keys")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}

def chunked(items: List[str], size: int):
    for i in range(0, len(items), size): yield items[i:i+size]

def parse_ts(v):
    if not v: return None
    try:
        t = str(v).replace("Z", "+00:00")
        dt = datetime.fromisoformat(t)
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except Exception: return None

def fetch_bars(symbols, start, end, feed, timeframe, hdrs):
    url = "https://data.alpaca.markets/v2/stocks/bars"
    q = urlencode({"symbols": ",".join(symbols), "timeframe": timeframe, "start": start.isoformat().replace("+00:00","Z"), "end": end.isoformat().replace("+00:00","Z"), "feed": feed, "limit": 10000})
    with urlopen(Request(f"{url}?{q}", headers=hdrs, method="GET"), timeout=30) as r:
        p = json.loads(r.read().decode("utf-8"))
    bars = p.get("bars") if isinstance(p, dict) else {}
    return {str(k).upper(): v for k, v in bars.items() if isinstance(v, list)} if isinstance(bars, dict) else {}

def fetch_snapshots(symbols, feed, hdrs):
    q = urlencode({"symbols": ",".join(symbols), "feed": feed})
    try:
        with urlopen(Request(f"https://data.alpaca.markets/v2/stocks/snapshots?{q}", headers=hdrs, method="GET"), timeout=30) as r:
            p = json.loads(r.read().decode("utf-8"))
        return p if isinstance(p, dict) else {}
    except Exception: return {}

def pct(c, b):
    if c is None or b in (None, 0): return None
    return (c-b)/b*100.0

def calc_vwap(bars):
    num = den = 0.0
    for b in bars:
        h,l,c,v = safe_float(b.get("h")), safe_float(b.get("l")), safe_float(b.get("c")), safe_float(b.get("v"),0) or 0
        if h is None or l is None or c is None or v <= 0: continue
        num += ((h+l+c)/3.0)*v; den += v
    return num/den if den > 0 else None

def volume_acceleration(bars):
    if len(bars) < 10: return None
    recent = sum((safe_float(x.get("v"),0) or 0) for x in bars[-5:])
    prior = sum((safe_float(x.get("v"),0) or 0) for x in bars[-10:-5])
    return recent/prior if prior > 0 else None

def trend_state(price, vwap):
    d = pct(price, vwap)
    if d is None: return "UNKNOWN"
    if d < 0: return "BELOW_VWAP"
    if d <= 4: return "BULLISH_CONTROLLED"
    if d <= 6: return "BULLISH_EXTENDED"
    return "CHASE_RISK"

def daily_baseline(symbols, feed, hdrs, days):
    end = now_utc() - timedelta(days=1); start = end - timedelta(days=max(days*2, 30))
    out = {}
    for ch in chunked(symbols, 100):
        try: bars = fetch_bars(ch, start, end, feed, "1Day", hdrs)
        except Exception: continue
        for s, bs in bars.items():
            vols = [safe_float(b.get("v")) for b in bs[-days:]]
            vols = [v for v in vols if v and v > 0]
            if vols: out[s] = statistics.mean(vols)
    return out

def candidate(symbol, bars, baseline, snapshot, feed):
    if not bars: return None
    last = bars[-1]; price = safe_float(last.get("c")); openp = safe_float(bars[0].get("o")); prev = None
    bid = None
    ask = None
    if isinstance(snapshot, dict):
        pd = snapshot.get("prevDailyBar")
        if isinstance(pd, dict): prev = safe_float(pd.get("c"))
        lt = snapshot.get("latestTrade")
        if price is None and isinstance(lt, dict): price = safe_float(lt.get("p"))
        lq = snapshot.get("latestQuote")
        if isinstance(lq, dict):
            bid = safe_float(lq.get("bp"))
            ask = safe_float(lq.get("ap"))
    if price is None or price <= 0: return None
    vwap = calc_vwap(bars); vol = sum((safe_float(b.get("v"),0) or 0) for b in bars)
    elapsed_fraction = max(1, min(len(bars), 390)) / 390
    expected_volume_so_far = baseline * elapsed_fraction if baseline and baseline > 0 else None
    rvol = vol/expected_volume_so_far if expected_volume_so_far and expected_volume_so_far > 0 else None
    spct = ((ask-bid)/((ask+bid)/2)*100) if bid and ask and ask >= bid else None
    gap = pct(price, prev); day = pct(price, openp); vd = pct(price, vwap); acc = volume_acceleration(bars)
    ts = parse_ts(last.get("t")); age = max(0.0, (now_utc()-ts).total_seconds()) if ts else None
    score = 0.0
    if day is not None: score += min(max(day,0),25)
    if rvol is not None: score += min(rvol*8,35)
    if vd is not None and 0 <= vd <= 6: score += 20
    if acc is not None and acc >= 1.25: score += 10
    return {"ticker": symbol, "symbol": symbol, "price": round(price,4), "bid": round(bid,4) if bid is not None else None, "ask": round(ask,4) if ask is not None else None, "spread_pct": round(spct,4) if spct is not None else None, "open": round(openp,4) if openp else None, "previous_close": round(prev,4) if prev else None, "gap_pct": round(gap,4) if gap is not None else None, "day_change_pct": round(day,4) if day is not None else None, "relative_volume": round(rvol,4) if rvol is not None else None, "rvol_method": "time_adjusted_intraday_volume_vs_scaled_20d_average_daily_volume", "vwap": round(vwap,4) if vwap else None, "vwap_distance_pct": round(vd,4) if vd is not None else None, "volume_acceleration": round(acc,4) if acc is not None else None, "trend_state": trend_state(price, vwap), "volume": int(vol), "baseline_daily_volume": round(baseline,2) if baseline else None, "score": round(score,4), "source_type":"alpaca_paid_market_scanner", "primary_source": f"alpaca_{feed}", "candidate_quality": "sip_paid" if feed == "sip" else "iex_fallback", "fallback_used": False, "data_age_seconds": round(age,2) if age is not None else None, "bar_count": len(bars), "bar_timeframe_used":"1Min", "generated_at": now_utc_iso()}

def run_scanner():
    st = get_paid_settings(); hdrs = headers(); universe = get_universe()[:st.max_symbols]
    end = now_utc(); start = end - timedelta(minutes=st.lookback_minutes)
    base = daily_baseline(universe, st.feed, hdrs, st.baseline_days)
    rows=[]; errors=[]
    for ch in chunked(universe, st.chunk_size):
        try: bars = fetch_bars(ch, start, end, st.feed, st.bar_timeframe, hdrs)
        except Exception as e:
            logging.error(f"bars_fetch_failed for chunk starting with {ch[:3]}: {e}")
            errors.append(f"bars_fetch_failed:{ch[:3]}:An error occurred while fetching bars")
            continue
        snaps = fetch_snapshots(ch, st.feed, hdrs)
        for s in ch:
            row = candidate(s, bars.get(s,[]), base.get(s), snaps.get(s) if isinstance(snaps, dict) else None, st.feed)
            if row: rows.append(row)
    rows.sort(key=lambda r:(float(r.get("score") or 0), float(r.get("relative_volume") or 0), float(r.get("day_change_pct") or 0)), reverse=True)
    payload={"schema_version":"alpaca_paid_market_scanner_v1","generated_at":now_utc_iso(),"status":"PASS" if rows else "WARN","mode":"paid_alpaca_sip_research","settings":{"feed":st.feed,"use_sip":st.use_sip,"max_symbols":st.max_symbols,"chunk_size":st.chunk_size,"bar_timeframe":st.bar_timeframe,"lookback_minutes":st.lookback_minutes,"baseline_days":st.baseline_days},"counts":{"universe_size":len(universe),"candidate_count":len(rows),"error_count":len(errors)},"errors":errors[:20],"candidates":rows[:100],"rows":rows[:100],"safety":{"paper_only":True,"order_submission":False,"live_trading":False,"feed_expected":"sip"}}
    health={"schema_version":"alpaca_paid_market_scanner_health_v1","generated_at":payload["generated_at"],"status":payload["status"],"feed":st.feed,"use_sip":st.use_sip,"candidate_count":len(rows),"universe_size":len(universe),"error_count":len(errors),"paper_only":True,"order_submission":False}
    write_json(OUTPUT_PATH,payload); write_json(DOCS_OUTPUT_PATH,payload); write_json(HEALTH_PATH,health)
    return {"status":payload["status"],"candidate_count":len(rows),"feed":st.feed,"output_path":str(OUTPUT_PATH),"health_path":str(HEALTH_PATH)}

def main(): print(json.dumps(run_scanner(), indent=2))
if __name__ == "__main__": main()
