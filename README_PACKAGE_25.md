# Package 25: Alert Delivery Layer

Adds alert delivery for the always-on Jini engine.

## Alerts

- System health alerts
- Final audit alerts
- Production monitor alerts
- Strong buy setup alerts
- Buy setup watch alerts
- Wait-for-pullback alerts

## Delivery

Telegram is supported with:

TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID

Optional:

ALERT_SEND_ENABLED=true
JINI_DASHBOARD_URL=https://agun420.github.io/jini/

## Outputs

- docs/data/prediction_engine/alert_delivery.json
- docs/data/prediction_engine/alert_delivery_health.json
- state/prediction_engine/alert_delivery.json
- state/prediction_engine/alert_history.json

## Safety

Alerting only.

- order_submission=false
- live_trading=false
- no automatic buying
- no live orders

## Run

PYTHONPATH=src:. python scripts/validate_alert_delivery_package.py
PYTHONPATH=src:. ALERT_SEND_ENABLED=false python scripts/run_alert_delivery.py
