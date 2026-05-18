from __future__ import annotations

import json
from pathlib import Path


REQUIRED = [
    "docs/assets/app.js",
    "docs/assets/styles.css",
    "scripts/validate_dashboard_safe_mode_ui_package.py",
    "README_PACKAGE_32.md",
]

APP_MARKERS = [
    "auth_failure_safe_mode_health.json",
    "signal_dashboard_safe_mode.json",
    "renderSafeModeBanner",
    "ALPACA AUTH FAILED",
    "SAFE MODE ACTIVE",
    "preferSafeModeSignals",
]

CSS_MARKERS = [
    ".safe-mode-banner",
    ".safe-mode-banner.danger",
    ".safe-mode-banner.ok",
]


def main() -> None:
    missing = [item for item in REQUIRED if not Path(item).exists()]

    app = Path("docs/assets/app.js").read_text(encoding="utf-8") if Path("docs/assets/app.js").exists() else ""
    css = Path("docs/assets/styles.css").read_text(encoding="utf-8") if Path("docs/assets/styles.css").exists() else ""

    missing_app = [item for item in APP_MARKERS if item not in app]
    missing_css = [item for item in CSS_MARKERS if item not in css]

    status = "PASS" if not missing and not missing_app and not missing_css else "FAIL"

    print(json.dumps({
        "status": status,
        "package": "Package 32 - Dashboard Safe-Mode UI Patch",
        "missing": missing,
        "missing_app_markers": missing_app,
        "missing_css_markers": missing_css,
    }, indent=2))

    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
