from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


OUT_PATH = Path("docs/data/prediction_engine/test_alert_health.json")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_valid_telegram_token(token: str | None) -> bool:
    if not token:
        return False
    return bool(re.match(r"^[0-9]+:[a-zA-Z0-9_-]+$", token))


def is_valid_telegram_chat_id(chat_id: str | None) -> bool:
    if not chat_id:
        return False
    return bool(re.match(r"^-?\d+$|^@[a-zA-Z0-9_]+$", chat_id))


def send_telegram(text: str) -> dict:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not is_valid_telegram_token(token) or not is_valid_telegram_chat_id(chat_id):
        return {
            "sent": False,
            "reason": "telegram_not_configured_or_invalid",
        }

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=15) as response:
            body = response.read().decode("utf-8", errors="ignore")
            return {
                "sent": True,
                "status_code": response.status,
                "response": body[:500],
            }
    except Exception as exc:
        return {
            "sent": False,
            "reason": "telegram_send_failed",
            "error": str(exc),
        }


def main() -> None:
    dashboard_url = os.getenv("JINI_DASHBOARD_URL", "https://agun420.github.io/jini/")

    message = (
        "JINI TEST ALERT\n"
        "Telegram alert delivery is working.\n"
        f"Time UTC: {now()}\n"
        f"Dashboard: {dashboard_url}\n"
        "Paper/research only. No live order submitted."
    )

    result = send_telegram(message)

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    payload = {
        "schema_version": "test_alert_health_v1",
        "generated_at": now(),
        "status": "PASS" if result.get("sent") else "FAIL",
        "telegram_configured": is_valid_telegram_token(token) and is_valid_telegram_chat_id(chat_id),
        "delivery_result": result,
        "order_submission": False,
        "live_trading": False,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(json.dumps(payload, indent=2))

    if payload["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
