from __future__ import annotations

import ast
import json
from pathlib import Path


REQUIRED = [
    "scripts/data_feed_truth_guard.py",
    "scripts/run_data_feed_truth_guard.py",
    "scripts/validate_data_feed_truth_guard_package.py",
    "README_PACKAGE_28.md",
]

MARKERS = [
    "DATA_FEED_FAIL",
    "zero_or_negative_price",
    "missing_price",
    "data_feed_quality_health.json",
    "signal_dashboard_data_guard_enriched.json",
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
        "package": "Package 28 - Data Feed Truth Check + Zero Price Guard",
        "missing": missing,
        "python_failures": python_failures,
        "missing_markers": missing_markers,
    }, indent=2))

    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
