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
    run("Run Alpaca Paid Market Scanner", [sys.executable,"-m","prediction_engine.scanners.alpaca_paid_market_scanner"])
    run("Run Free Scanner Normalizer", [sys.executable,"scripts/run_free_scanner_normalizer.py"], required=False)
    print(json.dumps({"status":"PASS","package":"Alpaca Paid Market Scanner"},indent=2))
if __name__=="__main__": main()
