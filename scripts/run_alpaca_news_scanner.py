from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

def run(name, cmd, required=True):
    print(f"\n=== {name} ===")
    r=subprocess.run(cmd,text=True,capture_output=True)
    if r.stdout: print(r.stdout)
    if r.stderr: print(r.stderr,file=sys.stderr)
    if required and r.returncode!=0: raise SystemExit(f"{name} failed with code {r.returncode}")

def main():
    Path("docs/data/prediction_engine").mkdir(parents=True,exist_ok=True); Path("state/prediction_engine").mkdir(parents=True,exist_ok=True)
    run("Run Alpaca News Scanner", [sys.executable,"-m","prediction_engine.catalysts.alpaca_news_scanner"])
    run("Enrich Dashboard With Alpaca News", [sys.executable,"-m","prediction_engine.catalysts.enrich_signal_dashboard_with_alpaca_news"], required=False)
    print(json.dumps({"status":"PASS","package":"Alpaca News Scanner"},indent=2))
if __name__=="__main__": main()
