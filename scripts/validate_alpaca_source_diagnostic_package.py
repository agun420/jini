from __future__ import annotations

import ast
import json
from pathlib import Path


REQUIRED = [
    "scripts/alpaca_source_diagnostic.py",
    "scripts/run_alpaca_source_diagnostic.py",
    "scripts/validate_alpaca_source_diagnostic_package.py",
    "README_PACKAGE_30.md",
]

MARKERS = [
    "alpaca_auth_failed_401",
    "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY",
    "DataFeed.IEX",
    "DataFeed.SIP",
    "alpaca_source_diagnostic_health.json",
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
        "package": "Package 30 - Alpaca Auth + Scanner Source Diagnostic",
        "missing": missing,
        "python_failures": python_failures,
        "missing_markers": missing_markers,
    }, indent=2))

    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
