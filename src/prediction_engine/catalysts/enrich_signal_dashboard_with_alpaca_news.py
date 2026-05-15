from __future__ import annotations
import json
from pathlib import Path
from typing import Any
NEWS_PATH=Path("docs/data/prediction_engine/alpaca_news.json")
DASHBOARD_CANDIDATES=[Path("docs/data/prediction_engine/signal_dashboard_finra_enriched.json"),Path("docs/data/prediction_engine/signal_dashboard_enriched.json"),Path("docs/data/prediction_engine/signal_dashboard.json")]
OUTPUT_PATH=Path("docs/data/prediction_engine/signal_dashboard_news_enriched.json")
def read_json(p:Path,d:Any):
    if not p.exists(): return d
    try: return json.loads(p.read_text(encoding="utf-8") or "{}")
    except Exception: return d
def write_json(p:Path,x:Any): p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(x,indent=2,sort_keys=False),encoding="utf-8")
def load_dash():
    for p in DASHBOARD_CANDIDATES:
        d=read_json(p,{})
        if isinstance(d,dict) and isinstance(d.get("rows"),list): d["_source_path"]=str(p); return d
    return {"rows":[],"_source_path":"none"}
def main():
    dash=load_dash(); news=read_json(NEWS_PATH,{})
    by={str(x.get("ticker") or "").upper():x for x in (news.get("symbol_summary") or []) if isinstance(x,dict) and x.get("ticker")}
    rows=[]
    for row in dash.get("rows",[]):
        if not isinstance(row,dict): continue
        t=str(row.get("ticker") or row.get("symbol") or "").upper(); r=dict(row)
        r["alpaca_news"]=by.get(t,{"ticker":t,"news_count":0,"news_catalyst_score":0,"risk_flags":[],"latest_headline":None,"latest_url":None})
        rows.append(r)
    dash["rows"]=rows; dash["schema_version"]="signal_dashboard_news_enriched_v1"; dash["alpaca_news_source"]=str(NEWS_PATH); dash["source_before_news"]=dash.get("_source_path"); dash.pop("_source_path",None)
    write_json(OUTPUT_PATH,dash)
    print(json.dumps({"status":"PASS","rows":len(rows),"output_path":str(OUTPUT_PATH)}, indent=2))
if __name__=="__main__": main()
