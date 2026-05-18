# Package 30: Alpaca Auth + Scanner Source Diagnostic

Adds diagnostics for Alpaca auth, market data feed access, and scanner source quality.

## Checks

- Alpaca paper trading account auth
- Alpaca IEX bars
- Alpaca IEX latest quotes
- Alpaca SIP bars
- Alpaca SIP latest quotes
- Current configured feed
- Scanner files with zero-price row counts
- Data guard/stabilizer outputs

## Outputs

- docs/data/prediction_engine/alpaca_source_diagnostic.json
- docs/data/prediction_engine/alpaca_source_diagnostic_health.json
- state/prediction_engine/alpaca_source_diagnostic.json

## Safety

Diagnostic only.

- order_submission=false
- live_trading=false
- no automatic buying
- no live orders

## Run

PYTHONPATH=src:. python scripts/validate_alpaca_source_diagnostic_package.py
PYTHONPATH=src:. python scripts/run_alpaca_source_diagnostic.py
