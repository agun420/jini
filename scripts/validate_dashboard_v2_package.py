from __future__ import annotations

import json
from pathlib import Path


REQUIRED_FILES = [
    "docs/index.html",
    "docs/assets/styles.css",
    "docs/assets/app.js",
    "README_PACKAGE_8.md",
]


def main() -> None:
    missing = [item for item in REQUIRED_FILES if not Path(item).exists()]
    if missing:
        raise SystemExit(f"Missing required files: {missing}")

    html = Path("docs/index.html").read_text(encoding="utf-8")
    app = Path("docs/assets/app.js").read_text(encoding="utf-8")
    css = Path("docs/assets/styles.css").read_text(encoding="utf-8")

    required_html_ids = [
        "metric-total-signals",
        "metric-trade-eligible",
        "adaptive-guard-panel",
        "paper-plan-panel",
        "outcomes-panel",
        "signals-table",
        "health-panel",
        "quality-panel",
        "learning-panel",
    ]

    missing_ids = [item for item in required_html_ids if item not in html]
    if missing_ids:
        raise SystemExit(f"Missing dashboard element ids: {missing_ids}")

    required_data_refs = [
        "signal_dashboard_finra_enriched.json",
        "adaptive_guard.json",
        "paper_order_plan.json",
        "outcomes.json",
        "learning.json",
    ]

    missing_refs = [item for item in required_data_refs if item not in app]
    if missing_refs:
        raise SystemExit(f"Missing app data references: {missing_refs}")

    if ".card" not in css:
        raise SystemExit("CSS appears incomplete; .card class missing.")

    print(
        json.dumps(
            {
                "status": "PASS",
                "message": "Package 8 dashboard validation passed.",
                "checked_files": REQUIRED_FILES,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
