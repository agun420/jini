# Package 28: Data Feed Truth Check + Zero Price Guard

Adds a data quality guard that blocks invalid market data rows from appearing as normal watch or buy candidates.

## Problem solved

When Alpaca auth or market data fails, scanner fallback rows can show:

- price = 0
- missing feed
- missing source
- repeated fallback scores

This package marks those rows as DATA_FEED_FAIL.

## Adds

- Zero price detection
- Missing price detection
- Missing feed/source detection
- Data feed quality health JSON
- Guarded dashboard JSON
- Buy setup alert blocking for invalid rows

## Outputs

- docs/data/prediction_engine/signal_dashboard_data_guard_enriched.json
- docs/data/prediction_engine/data_feed_quality_health.json
- state/prediction_engine/data_feed_quality.json

## Safety

Data quality guard only.

- order_submission=false
- live_trading=false
- no automatic buying
- no live orders

## Run

PYTHONPATH=src:. python scripts/validate_data_feed_truth_guard_package.py
PYTHONPATH=src:. python scripts/run_data_feed_truth_guard.py
