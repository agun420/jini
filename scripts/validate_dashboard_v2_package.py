from __future__ import annotations

import json
from pathlib import Path


REQUIRED_RUNTIME_FILES = [
    "docs/index.html",
    "docs/assets/styles.css",
    "docs/assets/app.js",
]

OPTIONAL_PACKAGE_FILES = [
    "README_PACKAGE_8.md",
]


RECOMMENDED_DATA_REFS = [
    "signal_dashboard_market_guard_enriched.json",
    "signal_dashboard_quality_enriched.json",
    "signal_dashboard_news_enriched.json",
    "signal_dashboard_finra_enriched.json",
    "signal_dashboard_enriched.json",
    "signal_dashboard.json",
    "adaptive_guard.json",
    "paper_order_plan.json",
    "outcomes.json",
    "learning.json",
]


RECOMMENDED_HTML_IDS = [
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


def main() -> None:
    missing_required = [
        item for item in REQUIRED_RUNTIME_FILES
        if not Path(item).exists()
    ]

    missing_optional = [
        item for item in OPTIONAL_PACKAGE_FILES
        if not Path(item).exists()
    ]

    html = Path("docs/index.html").read_text(encoding="utf-8") if Path("docs/index.html").exists() else ""
    app = Path("docs/assets/app.js").read_text(encoding="utf-8") if Path("docs/assets/app.js").exists() else ""
    css = Path("docs/assets/styles.css").read_text(encoding="utf-8") if Path("docs/assets/styles.css").exists() else ""

    missing_html_ids = [
        item for item in RECOMMENDED_HTML_IDS
        if item not in html
    ]

    missing_data_refs = [
        item for item in RECOMMENDED_DATA_REFS
        if item not in app
    ]

    css_checks = {
        "has_card_class": ".card" in css,
        "has_table_styles": "table" in css,
        "has_body_styles": "body" in css,
    }

    hard_css_failures = [
        key for key, value in css_checks.items()
        if not value
    ]

    payload = {
        "status": "PASS" if not missing_required and not hard_css_failures else "FAIL",
        "package": "Package 8 - Dashboard v2",
        "required_runtime_files": REQUIRED_RUNTIME_FILES,
        "optional_package_files": OPTIONAL_PACKAGE_FILES,
        "missing_required": missing_required,
        "missing_optional_warning_only": missing_optional,
        "missing_html_ids_warning_only": missing_html_ids,
        "missing_data_refs_warning_only": missing_data_refs,
        "css_checks": css_checks,
        "note": (
            "Dashboard validation requires index.html, styles.css, and app.js. "
            "Specific data references and README files are warnings because the dashboard can evolve."
        ),
    }

    print(json.dumps(payload, indent=2))

    if payload["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
