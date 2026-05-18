from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS_DIR = Path("docs/data/prediction_engine")
STATE_DIR = Path("state/prediction_engine")

INPUTS = {
    "runtime": DOCS_DIR / "runtime_heartbeat.json",
    "audit": DOCS_DIR / "final_repo_audit.json",
    "oracle_env": DOCS_DIR / "oracle_vm_env_check.json",
    "three_score": DOCS_DIR / "three_score_matrix_health.json",
    "second_leg": DOCS_DIR / "second_leg_health.json",
    "rvol": DOCS_DIR / "time_slot_rvol_health.json",
    "walk_forward": DOCS_DIR / "walk_forward_health.json",
    "meta_labeling": DOCS_DIR / "meta_labeling_health.json",
}

OUT_MONITOR = DOCS_DIR / "production_monitor.json"
OUT_HEALTH = DOCS_DIR / "production_monitor_health.json"
OUT_STATE = STATE_DIR / "production_monitor.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    try:
        raw = path.read_text(encoding="utf-8").strip()
        return json.loads(raw) if raw else default
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None

    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def age_minutes(value: Any) -> float | None:
    parsed = parse_dt(value)
    if parsed is None:
        return None
    delta = datetime.now(timezone.utc) - parsed
    return round(delta.total_seconds() / 60.0, 2)


def check_payload(name: str, path: Path) -> dict[str, Any]:
    payload = read_json(path, {})
    status = payload.get("status") if isinstance(payload, dict) else None

    generated_at = None
    if isinstance(payload, dict):
        generated_at = (
            payload.get("generated_at")
            or payload.get("checked_at")
            or payload.get("updated_at")
        )

    return {
        "name": name,
        "path": str(path),
        "exists": path.exists(),
        "status": status or "UNKNOWN",
        "generated_at": generated_at,
        "age_minutes": age_minutes(generated_at),
    }


def git_health() -> dict[str, Any]:
    try:
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            text=True,
            capture_output=True,
            timeout=8,
        )
        status = subprocess.run(
            ["git", "status", "--short"],
            text=True,
            capture_output=True,
            timeout=8,
        )
        log = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            text=True,
            capture_output=True,
            timeout=8,
        )

        return {
            "available": True,
            "branch": branch.stdout.strip(),
            "dirty_files": len([line for line in status.stdout.splitlines() if line.strip()]),
            "latest_commit": log.stdout.strip(),
        }
    except Exception as exc:
        return {
            "available": False,
            "error": str(exc),
        }


def build_monitor() -> dict[str, Any]:
    generated_at = now()
    checks = {name: check_payload(name, path) for name, path in INPUTS.items()}
    git = git_health()

    blockers: list[str] = []
    warnings: list[str] = []

    runtime_age = checks["runtime"]["age_minutes"]

    if not checks["runtime"]["exists"]:
        blockers.append("runtime_heartbeat_missing")
    elif runtime_age is not None and runtime_age > 15:
        blockers.append("runtime_heartbeat_stale_over_15_min")

    if checks["audit"]["status"] != "PASS":
        blockers.append("final_repo_audit_not_pass")

    for name in ["three_score", "second_leg", "rvol", "walk_forward", "meta_labeling"]:
        item = checks[name]
        if not item["exists"]:
            warnings.append(f"{name}_missing")
        elif item["status"] != "PASS":
            warnings.append(f"{name}_not_pass")

    oracle_env = read_json(INPUTS["oracle_env"], {})
    if isinstance(oracle_env, dict):
        env = oracle_env.get("env", {})
        if env.get("has_alpaca_key") is not True:
            warnings.append("alpaca_key_missing")
        if env.get("has_alpaca_secret") is not True:
            warnings.append("alpaca_secret_missing")
        if env.get("has_sec_user_agent") is not True:
            warnings.append("sec_user_agent_missing")
        if env.get("paper_order_submission_enabled") != "false":
            blockers.append("paper_order_submission_not_false")
        if env.get("manual_approval_required") != "true":
            blockers.append("manual_approval_not_true")
    else:
        warnings.append("oracle_env_check_missing")

    if git.get("dirty_files", 0) > 100:
        warnings.append("large_uncommitted_file_count")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    return {
        "schema_version": "production_monitor_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "checks": checks,
        "git": git,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "purpose": "Production health monitoring only. Does not submit orders.",
        },
    }


def export() -> dict[str, Any]:
    monitor = build_monitor()

    health = {
        "schema_version": "production_monitor_health_v1",
        "generated_at": monitor["generated_at"],
        "status": monitor["status"],
        "blocker_count": len(monitor["blockers"]),
        "warning_count": len(monitor["warnings"]),
        "blockers": monitor["blockers"],
        "warnings": monitor["warnings"],
        "order_submission": False,
        "live_trading": False,
    }

    write_json(OUT_MONITOR, monitor)
    write_json(OUT_STATE, monitor)
    write_json(OUT_HEALTH, health)

    return {
        "status": monitor["status"],
        "blockers": monitor["blockers"],
        "warnings": monitor["warnings"],
        "monitor_path": str(OUT_MONITOR),
        "health_path": str(OUT_HEALTH),
    }


def main() -> None:
    print(json.dumps(export(), indent=2))


if __name__ == "__main__":
    main()
