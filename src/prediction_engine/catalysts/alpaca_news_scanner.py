from __future__ import annotations
import json, os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from prediction_engine.scanners.alpaca_paid_config import get_paid_settings, get_universe

NEWS_OUTPUT_PATH = Path("docs/data/prediction_engine/alpaca_news.json")
NEWS_HEALTH_PATH = Path("docs/data/prediction_engine/alpaca_news_health.json")
NEWS_STATE_PATH = Path("state/prediction_engine/alpaca_news_cache.json")
DASHBOARD_CANDIDATES = [Path("docs/data/prediction_engine/signal_dashboard_finra_enriched.json"), Path("docs/data/prediction_engine/signal_dashboard_enriched.json"), Path("docs/data/prediction_engine/signal_dashboard.json")]
KEYWORDS = {"EARNINGS":["earnings","eps","revenue","guidance"],"FDA":["fda","approval","phase 1","phase 2","phase 3","clinical trial"],"DEAL":["acquisition","merger","buyout","takeover"],"CONTRACT":["contract","agreement","partnership","collaboration"],"ANALYST":["upgrade","downgrade","price target","initiated"],"OFFERING_RISK":["offering","shelf","atm","registered direct","warrant","dilution"]}

def now(): return datetime.now(timezone.utc)
def iso(): return now().isoformat()
def write_json(p: Path, x: Any): p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(x, indent=2, sort_keys=False), encoding="utf-8")
def read_json(p: Path, d: Any):
    if not p.exists(): return d
    try: return json.loads(p.read_text(encoding="utf-8") or "{}")
    except Exception: return d

def headers():
    k=os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID"); s=os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
    if not k or not s: raise RuntimeError("Missing Alpaca API keys")
    return {"APCA-API-KEY-ID":k,"APCA-API-SECRET-KEY":s}

def dashboard_symbols():
    for p in DASHBOARD_CANDIDATES:
        data=read_json(p,{})
        rows=data.get("rows") if isinstance(data,dict) else None
        if isinstance(rows,list) and rows:
            syms=sorted({str(r.get("ticker") or r.get("symbol") or "").upper() for r in rows if isinstance(r,dict) and (r.get("ticker") or r.get("symbol"))})
            if syms: return syms
    return get_universe()

def classify(headline, summary=""):
    text=f"{headline} {summary}".lower(); tags=[]; score=0; risk=False
    for tag, words in KEYWORDS.items():
        if any(w in text for w in words):
            tags.append(tag)
            if tag=="OFFERING_RISK": risk=True; score-=20
            elif tag in {"FDA","DEAL","CONTRACT","EARNINGS"}: score+=25
            elif tag=="ANALYST": score+=10
    if not tags: tags=["GENERAL_NEWS"]; score+=2
    return {"tags":tags,"news_catalyst_score":max(-50,min(100,score)),"risk_flag":"OFFERING_OR_DILUTION_RISK" if risk else "NO_NEWS_RISK_FLAG"}

def fetch_news(symbols, limit, hours):
    start=now()-timedelta(hours=hours)
    q=urlencode({"symbols":",".join(symbols),"start":start.isoformat().replace("+00:00","Z"),"end":now().isoformat().replace("+00:00","Z"),"limit":limit,"sort":"desc"})
    with urlopen(Request(f"https://data.alpaca.markets/v1beta1/news?{q}", headers=headers(), method="GET"), timeout=30) as r:
        p=json.loads(r.read().decode("utf-8"))
    return p.get("news") if isinstance(p,dict) and isinstance(p.get("news"),list) else []

def export_news():
    st=get_paid_settings(); syms=dashboard_symbols()[:st.max_symbols]; rows=[]; errors=[]
    if st.include_news:
        for i in range(0,len(syms),50):
            chunk=syms[i:i+50]
            try: items=fetch_news(chunk, st.news_limit, st.news_lookback_hours)
            except Exception as e: errors.append(f"news_fetch_failed:{chunk[:3]}:{e}"); continue
            for it in items:
                if not isinstance(it,dict): continue
                c=classify(str(it.get("headline") or ""), str(it.get("summary") or ""))
                rows.append({"id":it.get("id"),"headline":it.get("headline"),"summary":str(it.get("summary") or "")[:300],"source":it.get("source"),"created_at":it.get("created_at"),"updated_at":it.get("updated_at"),"url":it.get("url"),"symbols":it.get("symbols") if isinstance(it.get("symbols"),list) else [],"provider":"alpaca_news_benzinga",**c})
    by={}
    for r in rows:
        for s in r.get("symbols",[]): by.setdefault(str(s).upper(),[]).append(r)
    summary=[]
    for s,items in by.items():
        total=sum((x.get("news_catalyst_score") or 0) for x in items); risks=sorted({x.get("risk_flag") for x in items if x.get("risk_flag")!="NO_NEWS_RISK_FLAG"})
        summary.append({"ticker":s,"news_count":len(items),"news_catalyst_score":max(-50,min(100,total)),"risk_flags":risks,"latest_headline":items[0].get("headline"),"latest_url":items[0].get("url")})
    summary.sort(key=lambda x:(x["news_catalyst_score"],x["news_count"]), reverse=True)
    payload={"schema_version":"alpaca_news_scanner_v1","generated_at":iso(),"status":"PASS" if not errors else "WARN","mode":"paid_alpaca_news_research","settings":{"news_enabled":st.include_news,"lookback_hours":st.news_lookback_hours,"limit":st.news_limit,"symbol_count":len(syms)},"counts":{"news_rows":len(rows),"symbols_with_news":len(summary),"error_count":len(errors)},"errors":errors[:20],"symbol_summary":summary,"rows":rows[:500],"safety":{"paper_only":True,"order_submission":False,"news_cannot_create_trade_eligible_alone":True}}
    health={"schema_version":"alpaca_news_health_v1","generated_at":payload["generated_at"],"status":payload["status"],"news_rows":len(rows),"symbols_with_news":len(summary),"error_count":len(errors),"paper_only":True,"order_submission":False}
    write_json(NEWS_OUTPUT_PATH,payload); write_json(NEWS_STATE_PATH,payload); write_json(NEWS_HEALTH_PATH,health)
    return {"status":payload["status"],"news_rows":len(rows),"symbols_with_news":len(summary),"output_path":str(NEWS_OUTPUT_PATH),"health_path":str(NEWS_HEALTH_PATH)}

def main(): print(json.dumps(export_news(), indent=2))
if __name__=="__main__": main()
