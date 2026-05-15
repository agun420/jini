from __future__ import annotations
import ast,json
from pathlib import Path
REQUIRED=["src/prediction_engine/scanners/alpaca_paid_config.py","src/prediction_engine/scanners/alpaca_paid_market_scanner.py","src/prediction_engine/catalysts/alpaca_news_scanner.py","src/prediction_engine/catalysts/enrich_signal_dashboard_with_alpaca_news.py","scripts/run_alpaca_paid_market_scanner.py","scripts/run_alpaca_news_scanner.py",".github/workflows/master-paid-alpaca-pipeline.yml"]
def main():
    missing=[x for x in REQUIRED if not Path(x).exists()]
    if missing: raise SystemExit(f"Missing files: {missing}")
    for x in REQUIRED:
        if x.endswith('.py'): ast.parse(Path(x).read_text(encoding='utf-8'))
    print(json.dumps({"status":"PASS","message":"Alpaca paid upgrade validation passed."},indent=2))
if __name__=='__main__': main()
