from __future__ import annotations

import ast
import json
from pathlib import Path


REQUIRED = [
    "scripts/test_telegram_alert.py",
    "scripts/alert_dashboard_summary.py",
    "scripts/run_alert_dashboard_summary.py",
    "scripts/validate_alert_verification_package.py",
    "README_PACKAGE_26.md",
]

MARKERS = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "JINI TEST ALERT",
    "alert_dashboard_summary.json",
    "alert_dashboard_summary_health.json",
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

    joined = ""
    for item in REQUIRED:
        if Path(item).exists():
            joined += Path(item).read_text(encoding="utf-8", errors="ignore")

    missing_markers = [marker for marker in MARKERS if marker not in joined]

    status = "PASS" if not missing and not python_failures and not missing_markers else "FAIL"

    print(json.dumps({
        "status": status,
        "package": "Package 26 - Alert Verification Dashboard",
        "missing": missing,
        "python_failures": python_failures,
        "missing_markers": missing_markers,
    }, indent=2))

    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
