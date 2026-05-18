# Package 24: Production Monitor

Adds production health monitoring for the always-on Jini engine.

## Checks

- Runtime heartbeat freshness
- Final repo audit status
- Three-score matrix status
- Second-leg FSM status
- Time-slot RVOL status
- Walk-forward testing status
- ML meta-labeling status
- Oracle VM environment check
- Git repo status

## Outputs

- docs/data/prediction_engine/production_monitor.json
- docs/data/prediction_engine/production_monitor_health.json
- state/prediction_engine/production_monitor.json

## Safety

This package is monitoring only.

- order_submission=false
- live_trading=false

## Run

PYTHONPATH=src:. python scripts/validate_production_monitor_package.py
PYTHONPATH=src:. python scripts/run_production_monitor.py
