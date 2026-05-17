from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any


REQUIRED_FILES = [
    "scripts/runtime_loop.sh",
    "scripts/run_runtime_worker.py",
    "scripts/run_local_dashboard.sh",
    "scripts/install_oracle_vm_service.sh",
    "docs/index.html",
    "docs/assets/app.js",
    "docs/assets/styles.css",
]

EXPECTED_SAFE_DEFAULTS = {
    "PAPER_ORDER_SUBMISSION_ENABLED": "false",
    "MANUAL_APPROVAL_REQUIRED": "true",
}


def bool_env(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "y", "on"}


def read_env_file() -> dict[str, str]:
    path = Path(".env")
    values: dict[str, str] = {}

    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")

    return values


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def systemctl_exists() -> bool:
    return command_exists("systemctl")


def service_status(service_name: str) -> dict[str, Any]:
    if not systemctl_exists():
        return {
            "available": False,
            "status": "SKIPPED",
            "reason": "systemctl_not_available",
        }

    result = subprocess.run(
        ["systemctl", "is-enabled", service_name],
        text=True,
        capture_output=True,
    )

    active = subprocess.run(
        ["systemctl", "is-active", service_name],
        text=True,
        capture_output=True,
    )

    return {
        "available": True,
        "enabled": result.stdout.strip() or result.stderr.strip(),
        "active": active.stdout.strip() or active.stderr.strip(),
        "enabled_returncode": result.returncode,
        "active_returncode": active.returncode,
    }


def main() -> None:
    env_file = read_env_file()

    alpaca_key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID") or env_file.get("ALPACA_API_KEY") or env_file.get("APCA_API_KEY_ID")
    alpaca_secret = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY") or env_file.get("ALPACA_SECRET_KEY") or env_file.get("APCA_API_SECRET_KEY")
    sec_user_agent = os.getenv("SEC_USER_AGENT") or env_file.get("SEC_USER_AGENT")

    paper_submission = (
        os.getenv("PAPER_ORDER_SUBMISSION_ENABLED")
        or env_file.get("PAPER_ORDER_SUBMISSION_ENABLED")
        or "false"
    ).lower()

    manual_approval = (
        os.getenv("MANUAL_APPROVAL_REQUIRED")
        or env_file.get("MANUAL_APPROVAL_REQUIRED")
        or "true"
    ).lower()

    missing_files = [item for item in REQUIRED_FILES if not Path(item).exists()]
    warnings = []
    blockers = []

    if missing_files:
        blockers.append("missing_required_files")

    if not Path(".env").exists():
        warnings.append("env_file_missing")

    if not alpaca_key or not alpaca_secret:
        warnings.append("alpaca_keys_missing")

    if not sec_user_agent:
        warnings.append("sec_user_agent_missing")

    if paper_submission != "false":
        blockers.append("paper_order_submission_not_false")

    if manual_approval != "true":
        blockers.append("manual_approval_not_true")

    if not command_exists("python3") and not command_exists("python"):
        blockers.append("python_missing")

    payload = {
        "status": "PASS" if not blockers else "FAIL",
        "package": "Package 23 - Oracle VM Deployment Finalization",
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "python": platform.python_version(),
        },
        "repo": {
            "cwd": str(Path.cwd()),
            "has_git": Path(".git").exists(),
        },
        "env": {
            "env_file_exists": Path(".env").exists(),
            "has_alpaca_key": bool(alpaca_key),
            "has_alpaca_secret": bool(alpaca_secret),
            "has_sec_user_agent": bool(sec_user_agent),
            "paper_order_submission_enabled": paper_submission,
            "manual_approval_required": manual_approval,
        },
        "services": {
            "jini_runtime": service_status("jini-runtime"),
            "jini_dashboard": service_status("jini-dashboard"),
        },
        "missing_files": missing_files,
        "warnings": warnings,
        "blockers": blockers,
        "safe_defaults": EXPECTED_SAFE_DEFAULTS,
    }

    print(json.dumps(payload, indent=2))

    Path("docs/data/prediction_engine").mkdir(parents=True, exist_ok=True)
    Path("state/prediction_engine").mkdir(parents=True, exist_ok=True)

    Path("docs/data/prediction_engine/oracle_vm_env_check.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    Path("state/prediction_engine/oracle_vm_env_check.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )

    if payload["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
