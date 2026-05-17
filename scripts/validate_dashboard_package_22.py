from __future__ import annotations

import json
from pathlib import Path


REQUIRED = [
    "docs/index.html",
    "docs/assets/app.js",
    "docs/assets/styles.css",
    "scripts/validate_dashboard_package_22.py",
    "README_PACKAGE_22.md",
]

REQUIRED_APP_MARKERS = [
    "meta_labeling_predictions.json",
    "three_score_matrix_health.json",
    "second_leg_health.json",
    "time_slot_rvol_health.json",
    "walk_forward_health.json",
]

REQUIRED_HTML_MARKERS = [
    "Three-Score Matrix",
    "Second-Leg FSM",
    "Time-Slot RVOL",
    "Walk-Forward",
    "ML Meta Label",
]


def main() -> None:
    missing = [item for item in REQUIRED if not Path(item).exists()]

    app_text = Path("docs/assets/app.js").read_text(encoding="utf-8") if Path("docs/assets/app.js").exists() else ""
    html_text = Path("docs/index.html").read_text(encoding="utf-8") if Path("docs/index.html").exists() else ""

    missing_app_markers = [item for item in REQUIRED_APP_MARKERS if item not in app_text]
    missing_html_markers = [item for item in REQUIRED_HTML_MARKERS if item not in html_text]

    status = "PASS"
    if missing or missing_app_markers or missing_html_markers:
        status = "FAIL"

    payload = {
        "status": status,
        "package": "Package 22 - Dashboard Integration",
        "missing": missing,
        "missing_app_markers": missing_app_markers,
        "missing_html_markers": missing_html_markers,
    }

    print(json.dumps(payload, indent=2))

    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()