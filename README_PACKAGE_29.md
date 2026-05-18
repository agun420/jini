# Package 29: Scanner Data Source Stabilizer

Prevents bad scanner cycles from overwriting good market data with zero-price fallback rows.

## Problem solved

When the scanner has a bad data cycle, it can output:

- price = 0
- missing feed
- missing source
- fallback rows

Package 29 creates a last-good-data cache and restores the last valid row when current scanner data is invalid.

## Adds

- Last good scanner row cache
- Stable dashboard JSON
- Scanner data source health JSON
- STALE_DATA_RESTORED status
- DATA_FEED_FAIL status when no current or cached price exists
- Buy alert blocking for stale or failed data

## Outputs

- docs/data/prediction_engine/signal_dashboard_stable.json
- docs/data/prediction_engine/scanner_data_source_health.json
- state/prediction_engine/last_good_signal_rows.json
- state/prediction_engine/scanner_data_source_health.json

## Safety

Data stabilizer only.

- order_submission=false
- live_trading=false
- no automatic buying
- no live orders

## Run

PYTHONPATH=src:. python scripts/validate_scanner_data_source_stabilizer_package.py
PYTHONPATH=src:. python scripts/run_scanner_data_source_stabilizer.py
