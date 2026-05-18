from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS_DIR = Path("docs/data/prediction_engine")
STATE_DIR = Path("state/prediction_engine")

ALERT_HEALTH = DOCS_DIR / "alert_delivery_health.json"
ALERT_DETAIL = DOCS_DIR / "alert_delivery.json"
ALERT_HISTORY = STATE_DIR / "alert_history.json"
PRODUCTION_MONITOR = DOCS_DIR / "production_monitor_health.json"
TEST_ALERT = DOCS_DIR / "test_alert_health.json"

OUT_PATH = DOCS_DIR / "alert_dashboard_summary.json"
OUT_HEALTH = DOCS_DIR / "alert_dashboard_summary_health.json"
OUT_STATE = STATE_DIR / "alert_dashboard_summary.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    try:
        raw = path.read_text(encoding="utf-8").strip()
        return json.loads(raw) if raw else default
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    alert_health = read_json(ALERT_HEALTH, {})
    alert_detail = read_json(ALERT_DETAIL, {})
    alert_history = read_json(ALERT_HISTORY, {"sent": {}})
    production_monitor = read_json(PRODUCTION_MONITOR, {})
    test_alert = read_json(TEST_ALERT, {})

    sent = alert_history.get("sent", {}) if isinstance(alert_history, dict) else {}
    sent_items = list(sent.values()) if isinstance(sent, dict) else []

    delivered = alert_detail.get("delivered", []) if isinstance(alert_detail, dict) else []
    skipped = alert_detail.get("skipped", []) if isinstance(alert_detail, dict) else []
    alerts = alert_detail.get("alerts", []) if isinstance(alert_detail, dict) else []

    buy_kinds = {"STRONG_BUY_SETUP_ALERT", "BUY_SETUP_WATCH", "WAIT_FOR_PULLBACK_ALERT"}

    delivered_buy_alerts = [item for item in delivered if item.get("kind") in buy_kinds]
    delivered_system_alerts = [item for item in delivered if item.get("kind") == "SYSTEM_HEALTH_ALERT"]
    candidate_buy_alerts = [item for item in alerts if item.get("kind") in buy_kinds]
    candidate_system_alerts = [item for item in alerts if item.get("kind") == "SYSTEM_HEALTH_ALERT"]

    payload = {
        "schema_version": "alert_dashboard_summary_v1",
        "generated_at": now(),
        "status": "PASS",
        "telegram_configured": alert_health.get("telegram_configured", False),
        "alert_health_status": alert_health.get("status", "UNKNOWN"),
        "production_monitor_status": production_monitor.get("status", "UNKNOWN"),
        "test_alert_status": test_alert.get("status", "NOT_RUN"),
        "candidate_alert_count": alert_health.get("candidate_alert_count", 0),
        "delivered_count": alert_health.get("delivered_count", 0),
        "skipped_count": alert_health.get("skipped_count", 0),
        "history_sent_count": len(sent_items),
        "last_sent_alert": sent_items[-1] if sent_items else None,
        "latest_delivered": delivered[-5:],
        "latest_skipped": skipped[-5:],
        "candidate_buy_alert_count": len(candidate_buy_alerts),
        "candidate_system_alert_count": len(candidate_system_alerts),
        "buy_alert_count_latest_run": len(delivered_buy_alerts),
        "system_alert_count_latest_run": len(delivered_system_alerts),
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "purpose": "Dashboard summary for alert delivery. Does not submit orders.",
        },
    }

    health = {
        "schema_version": "alert_dashboard_summary_health_v1",
        "generated_at": payload["generated_at"],
        "status": "PASS",
        "telegram_configured": payload["telegram_configured"],
        "alert_health_status": payload["alert_health_status"],
        "history_sent_count": payload["history_sent_count"],
        "order_submission": False,
        "live_trading": False,
    }

    write_json(OUT_PATH, payload)
    write_json(OUT_STATE, payload)
    write_json(OUT_HEALTH, health)

    print(json.dumps({
        "status": "PASS",
        "summary_path": str(OUT_PATH),
        "health_path": str(OUT_HEALTH),
        "telegram_configured": payload["telegram_configured"],
        "history_sent_count": payload["history_sent_count"],
        "delivered_count": payload["delivered_count"],
    }, indent=2))


if __name__ == "__main__":
    main()
