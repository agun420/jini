# Package 31: Auth-Failure Safe Mode

Adds a safe-mode layer for Alpaca authentication or data-feed failures.

## Problem solved

When Alpaca returns 401 or all data feed tests fail, the dashboard should not show normal watch/buy candidates.

Package 31 marks rows as ALPACA_AUTH_FAIL and blocks buy setup alerts while auth is failing.

## Adds

- Auth-failure safe mode health JSON
- Safe-mode dashboard JSON
- ALPACA_AUTH_FAIL score status
- Buy setup alert blocking
- Paper/live order blocking
- Clear dashboard-ready auth failure reason

## Outputs

- docs/data/prediction_engine/signal_dashboard_safe_mode.json
- docs/data/prediction_engine/auth_failure_safe_mode_health.json
- state/prediction_engine/auth_failure_safe_mode.json

## Safety

Safe-mode only.

- order_submission=false
- live_trading=false
- no automatic buying
- no live orders

## Run

PYTHONPATH=src:. python scripts/validate_auth_failure_safe_mode_package.py
PYTHONPATH=src:. python scripts/run_auth_failure_safe_mode.py
