from __future__ import annotations

import ast
import json
from pathlib import Path


REQUIRED = [
    "scripts/alert_delivery.py",
    "scripts/run_alert_delivery.py",
    "scripts/validate_alert_delivery_package.py",
    "README_PACKAGE_25.md",
]

REQUIRED_MARKERS = [
    "STRONG_BUY_SETUP_ALERT",
    "BUY_SETUP_WATCH",
    "WAIT_FOR_PULLBACK_ALERT",
    "SYSTEM_HEALTH_ALERT",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "order_submission",
    "live_trading",
]


def main() -> None:
    missing = [item for item in REQUIRED if not Path(item).exists()]

    python_failures = []
    for item in REQUIRED:
        if item.endswith(".py") and Path(item).exists():
            try:
                ast.parse(Path(item).read_text(encoding="utf-8"))
            except Exception as exc:
                python_failures.append({"file": item, "error": str(exc)})

    alert_text = Path("scripts/alert_delivery.py").read_text(encoding="utf-8") if Path("scripts/alert_delivery.py").exists() else ""
    missing_markers = [item for item in REQUIRED_MARKERS if item not in alert_text]

    status = "PASS" if not missing and not python_failures and not missing_markers else "FAIL"

    print(json.dumps({
        "status": status,
        "package": "Package 25 - Alert Delivery Layer",
        "missing": missing,
        "python_failures": python_failures,
        "missing_markers": missing_markers,
    }, indent=2))

    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
