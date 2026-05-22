from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

CHECK_FILES = {
    "package_100": DOCS / "v3_package_100_validation_health.json",
    "morning": DOCS / "v3_morning_readiness_report_health.json",
    "tomorrow_pack": DOCS / "v3_tomorrow_morning_command_pack_health.json",
    "paper_plan": DOCS / "v3_paper_order_plan_health.json",
    "edge_model": DOCS / "v3_mathematical_edge_model_health.json",
    "daily_report": DOCS / "v3_daily_research_report_health.json",
    "final_repo_audit": DOCS / "final_repo_audit.json",
}

OUT_DOCS = DOCS / "v3_hard_safety_lock.json"
OUT_HEALTH = DOCS / "v3_hard_safety_lock_health.json"
OUT_STATE = STATE / "v3_hard_safety_lock.json"

TRUE_VALUES = {"1", "true", "yes", "y", "on", "enabled"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return json.loads(raw) if raw else default
    except Exception as exc:
        return {"_read_error": str(exc), "_path": str(path)}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def env_true(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in TRUE_VALUES


def safe_score_blockers(payload: dict[str, Any]) -> list[str]:
    score = payload.get("score")
    if isinstance(score, dict):
        blockers = score.get("blockers", [])
        return blockers if isinstance(blockers, list) else []
    return []


def get_status(payload: dict[str, Any]) -> str:
    status = payload.get("status")
    if status:
        return str(status)

    score = payload.get("score")
    if isinstance(score, dict):
        return str(score.get("grade") or "UNKNOWN")

    return "UNKNOWN"


def main() -> None:
    generated_at = now_iso()

    blockers: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}

    env_checks = {
        "PAPER_ORDER_SUBMISSION_ENABLED": os.getenv("PAPER_ORDER_SUBMISSION_ENABLED"),
        "ORDER_SUBMISSION_ENABLED": os.getenv("ORDER_SUBMISSION_ENABLED"),
        "LIVE_TRADING": os.getenv("LIVE_TRADING"),
        "REAL_MONEY_TRADING": os.getenv("REAL_MONEY_TRADING"),
        "ALPACA_PAPER": os.getenv("ALPACA_PAPER"),
    }

    if env_true("LIVE_TRADING"):
        blockers.append("env_live_trading_true")
    if env_true("REAL_MONEY_TRADING"):
        blockers.append("env_real_money_trading_true")
    if env_true("PAPER_ORDER_SUBMISSION_ENABLED"):
        blockers.append("env_paper_order_submission_enabled_true")
    if env_true("ORDER_SUBMISSION_ENABLED"):
        blockers.append("env_order_submission_enabled_true")

    for name, path in CHECK_FILES.items():
        payload = read_json(path, {})
        if not isinstance(payload, dict):
            payload = {"_invalid_payload_type": type(payload).__name__}

        exists = path.exists()
        status = get_status(payload)
        file_blockers = payload.get("blockers", [])
        if not isinstance(file_blockers, list):
            file_blockers = []
        file_blockers += safe_score_blockers(payload)

        checks[name] = {
            "path": str(path),
            "exists": exists,
            "status": status,
            "order_submission": payload.get("order_submission"),
            "live_trading": payload.get("live_trading"),
            "paper_order_allowed": payload.get("paper_order_allowed"),
            "paper_trade_ready": payload.get("paper_trade_ready"),
            "blockers": file_blockers,
        }

        if not exists:
            blockers.append(f"missing_{name}")
            continue

        if status == "FAIL":
            blockers.append(f"{name}_fail")

        if payload.get("order_submission") is True:
            blockers.append(f"{name}_order_submission_true")

        if payload.get("live_trading") is True:
            blockers.append(f"{name}_live_trading_true")

        if payload.get("paper_order_allowed") is True:
            warnings.append(f"{name}_paper_order_allowed_true")

        if payload.get("paper_trade_ready") is True:
            warnings.append(f"{name}_paper_trade_ready_true_but_hard_lock_keeps_submission_off")

    package_100 = checks.get("package_100", {})
    if package_100.get("status") not in {"PASS", "WARN"}:
        blockers.append("package_100_not_pass")

    final_repo = checks.get("final_repo_audit", {})
    if final_repo.get("status") != "PASS":
        blockers.append("final_repo_audit_not_pass")

    safe_for_research = len(blockers) == 0
    safe_for_paper_submission = False
    safe_for_live_trading = False

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "v3_hard_safety_lock_health_v2",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "safe_for_research": safe_for_research,
        "safe_for_paper_plan_only": safe_for_research,
        "safe_for_paper_submission": safe_for_paper_submission,
        "safe_for_live_trading": safe_for_live_trading,
        "env_live_trading": env_checks.get("LIVE_TRADING"),
        "env_paper_order_submission_enabled": env_checks.get("PAPER_ORDER_SUBMISSION_ENABLED"),
        "paper_trade_ready": False,
        "paper_order_allowed": False,
        "order_submission": False,
        "live_trading": False,
    }

    out = {
        "schema_version": "v3_hard_safety_lock_v2",
        "generated_at": generated_at,
        "health": health,
        "env_checks": env_checks,
        "checks": checks,
        "decision": {
            "run_mode": "RESEARCH_ONLY_AND_PAPER_PLAN_ONLY",
            "safe_for_research": safe_for_research,
            "safe_for_paper_plan_only": safe_for_research,
            "safe_for_paper_submission": False,
            "safe_for_live_trading": False,
            "reason": "Hard safety lock keeps all submissions disabled until multi-day validation is complete.",
        },
        "safety": {
            "paper_trade_ready": False,
            "paper_order_allowed": False,
            "order_submission": False,
            "live_trading": False,
        },
    }

    write_json(OUT_DOCS, out)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, out)

    print(json.dumps(health, indent=2))

    if status == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
