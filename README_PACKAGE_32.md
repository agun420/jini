# Package 32: Dashboard Safe-Mode UI Patch

Adds a dashboard warning banner for Alpaca auth/data failure safe mode.

## Adds visibility for

- ALPACA AUTH FAILED
- SAFE MODE ACTIVE
- Buy alerts blocked
- Paper orders blocked
- Live orders blocked
- Safe-mode signal rows from signal_dashboard_safe_mode.json

## Updated files

- docs/assets/app.js
- docs/assets/styles.css
- scripts/validate_dashboard_safe_mode_ui_package.py

## Safety

Dashboard only.

- order_submission=false
- live_trading=false
- no automatic buying
- no live orders

## Validate

PYTHONPATH=src:. python scripts/validate_dashboard_safe_mode_ui_package.py
PYTHONPATH=src:. python scripts/run_final_repo_audit.py
