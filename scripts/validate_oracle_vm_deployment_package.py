from __future__ import annotations

import ast
import json
from pathlib import Path


REQUIRED = [
    "scripts/oracle_vm_env_check.py",
    "scripts/oracle_vm_health_check.sh",
    "scripts/oracle_vm_start_services.sh",
    "scripts/oracle_vm_stop_services.sh",
    "scripts/oracle_vm_status.sh",
    "scripts/validate_oracle_vm_deployment_package.py",
    "scripts/install_oracle_vm_service.sh",
    "scripts/runtime_loop.sh",
    "scripts/run_local_dashboard.sh",
    "README_PACKAGE_23.md",
]

REQUIRED_SHELL_MARKERS = {
    "scripts/oracle_vm_health_check.sh": ["run_runtime_worker.py", "run_final_repo_audit.py"],
    "scripts/oracle_vm_start_services.sh": ["jini-runtime", "jini-dashboard"],
    "scripts/oracle_vm_stop_services.sh": ["jini-runtime", "jini-dashboard"],
    "scripts/oracle_vm_status.sh": ["jini-runtime", "jini-dashboard"],
}


def main() -> None:
    missing = [item for item in REQUIRED if not Path(item).exists()]

    python_failures = []
    for item in REQUIRED:
        if item.endswith(".py") and Path(item).exists():
            try:
                ast.parse(Path(item).read_text(encoding="utf-8"))
            except Exception as exc:
                python_failures.append({"file": item, "error": str(exc)})

    shell_marker_failures = []
    for path, markers in REQUIRED_SHELL_MARKERS.items():
        text = Path(path).read_text(encoding="utf-8") if Path(path).exists() else ""
        for marker in markers:
            if marker not in text:
                shell_marker_failures.append({"file": path, "missing_marker": marker})

    status = "PASS" if not missing and not python_failures and not shell_marker_failures else "FAIL"

    payload = {
        "status": status,
        "package": "Package 23 - Oracle VM Deployment Finalization",
        "missing": missing,
        "python_failures": python_failures,
        "shell_marker_failures": shell_marker_failures,
    }

    print(json.dumps(payload, indent=2))

    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
