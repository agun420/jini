from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


DOCS_DIR = Path("docs/data/prediction_engine")
STATE_DIR = Path("state/prediction_engine")

HEARTBEAT_PATH = DOCS_DIR / "runtime_heartbeat.json"
STATUS_PATH = DOCS_DIR / "runtime_status.json"
STATE_PATH = STATE_DIR / "runtime_status.json"

DEFAULT_INTERVAL_SECONDS = 60
DEFAULT_SCRIPT_TIMEOUT_SECONDS = 180


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")


def bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw is not None and raw != "" else default
    except Exception:
        return default


def has_alpaca_keys() -> bool:
    return bool(os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")) and bool(
        os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
    )


def has_sec_user_agent() -> bool:
    return bool(os.getenv("SEC_USER_AGENT"))


def script_exists(script: str) -> bool:
    return Path(script).exists()


def safe_env() -> Dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = env.get("PYTHONPATH", "src:.")
    env["PAPER_ORDER_SUBMISSION_ENABLED"] = env.get("PAPER_ORDER_SUBMISSION_ENABLED", "false")
    env["MANUAL_APPROVAL_REQUIRED"] = env.get("MANUAL_APPROVAL_REQUIRED", "true")
    env["ENGINE_KILL_SWITCH"] = env.get("ENGINE_KILL_SWITCH", "false")
    return env


def run_script(script: str, *, required: bool = False, reason_if_skipped: str | None = None) -> Dict[str, Any]:
    started_at = now_utc_iso()

    if not script_exists(script):
        return {
            "script": script,
            "status": "SKIPPED",
            "required": required,
            "reason": "script_missing",
            "started_at": started_at,
            "finished_at": now_utc_iso(),
        }

    timeout = int_env("RUNTIME_SCRIPT_TIMEOUT_SECONDS", DEFAULT_SCRIPT_TIMEOUT_SECONDS)

    try:
        result = subprocess.run(
            [sys.executable, script],
            text=True,
            capture_output=True,
            timeout=timeout,
            env=safe_env(),
        )

        status = "PASS" if result.returncode == 0 else "FAIL"
        if result.returncode != 0 and not required:
            status = "WARN"

        return {
            "script": script,
            "status": status,
            "required": required,
            "returncode": result.returncode,
            "started_at": started_at,
            "finished_at": now_utc_iso(),
            "stdout_tail": result.stdout[-3000:],
            "stderr_tail": result.stderr[-3000:],
        }

    except subprocess.TimeoutExpired as exc:
        return {
            "script": script,
            "status": "FAIL" if required else "WARN",
            "required": required,
            "returncode": "TIMEOUT",
            "started_at": started_at,
            "finished_at": now_utc_iso(),
            "stdout_tail": (exc.stdout or "")[-3000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-3000:] if isinstance(exc.stderr, str) else "",
            "reason": f"timeout_after_{timeout}_seconds",
        }
    except Exception as exc:
        return {
            "script": script,
            "status": "FAIL" if required else "WARN",
            "required": required,
            "started_at": started_at,
            "finished_at": now_utc_iso(),
            "reason": str(exc),
        }


def runtime_plan() -> List[Dict[str, Any]]:
    plan: List[Dict[str, Any]] = []

    if has_alpaca_keys():
        plan.append({"script": "scripts/run_alpaca_paid_market_scanner.py", "required": False})
        plan.append({"script": "scripts/run_alpaca_news_scanner.py", "required": False})
    else:
        plan.append({
            "script": "scripts/run_alpaca_paid_market_scanner.py",
            "skip": True,
            "reason": "missing_alpaca_keys",
        })
        plan.append({
            "script": "scripts/run_alpaca_news_scanner.py",
            "skip": True,
            "reason": "missing_alpaca_keys",
        })

    if has_sec_user_agent():
        plan.append({"script": "scripts/run_sec_catalyst_scanner.py", "required": False})
    else:
        plan.append({
            "script": "scripts/run_sec_catalyst_scanner.py",
            "skip": True,
            "reason": "missing_sec_user_agent",
        })

    plan.extend([
        {"script": "scripts/run_finra_short_pressure_scanner.py", "required": False},
        {"script": "scripts/run_free_scanner_normalizer.py", "required": False},
        {"script": "scripts/run_advanced_signal_quality.py", "required": False},
        {"script": "scripts/run_halt_luld_circuit_guard.py", "required": False},
        {"script": "scripts/run_signal_journal.py", "required": False},
        {"script": "scripts/run_outcome_labeler.py", "required": False},
        {"script": "scripts/run_adaptive_guard.py", "required": False},
        {"script": "scripts/run_paper_execution_gate.py", "required": False},
        {"script": "scripts/run_slippage_fill_tracker.py", "required": False},
        {"script": "scripts/run_real_money_readiness_guard.py", "required": False},
        {"script": "scripts/write_paid_pipeline_health.py", "required": False},
        {"script": "scripts/run_final_repo_audit.py", "required": False},
    ])

    return plan


def run_once() -> Dict[str, Any]:
    started_at = now_utc_iso()

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, Any]] = []

    for item in runtime_plan():
        if item.get("skip"):
            results.append({
                "script": item["script"],
                "status": "SKIPPED",
                "reason": item.get("reason", "skipped_by_runtime_plan"),
                "started_at": now_utc_iso(),
                "finished_at": now_utc_iso(),
            })
            continue

        results.append(run_script(item["script"], required=bool(item.get("required"))))

    hard_failures = [
        result for result in results
        if result.get("required") and result.get("status") == "FAIL"
    ]

    warning_count = sum(1 for result in results if result.get("status") == "WARN")
    skipped_count = sum(1 for result in results if result.get("status") == "SKIPPED")

    status = "PASS" if not hard_failures else "FAIL"

    payload = {
        "schema_version": "jini_runtime_worker_v1",
        "generated_at": now_utc_iso(),
        "started_at": started_at,
        "finished_at": now_utc_iso(),
        "status": status,
        "mode": "always_on_runtime_worker",
        "counts": {
            "steps": len(results),
            "warnings": warning_count,
            "skipped": skipped_count,
            "hard_failures": len(hard_failures),
        },
        "results": results,
        "safety": {
            "paper_order_submission_enabled": bool_env("PAPER_ORDER_SUBMISSION_ENABLED", False),
            "live_trading_enabled": False,
            "real_money_automation_enabled": False,
            "manual_approval_required": bool_env("MANUAL_APPROVAL_REQUIRED", True),
            "engine_kill_switch": bool_env("ENGINE_KILL_SWITCH", False),
            "purpose": "Always-on scanner runtime. Does not enable live trading.",
        },
    }

    heartbeat = {
        "schema_version": "jini_runtime_heartbeat_v1",
        "generated_at": payload["generated_at"],
        "status": status,
        "mode": payload["mode"],
        "has_alpaca_keys": has_alpaca_keys(),
        "has_sec_user_agent": has_sec_user_agent(),
        "paper_order_submission_enabled": payload["safety"]["paper_order_submission_enabled"],
        "live_trading_enabled": False,
        "real_money_automation_enabled": False,
        "warning_count": warning_count,
        "skipped_count": skipped_count,
    }

    write_json(STATUS_PATH, payload)
    write_json(STATE_PATH, payload)
    write_json(HEARTBEAT_PATH, heartbeat)

    return payload


def loop_forever() -> None:
    interval = int_env("RUNTIME_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)

    while True:
        print(f"===== Jini runtime loop {now_utc_iso()} =====", flush=True)
        payload = run_once()
        print(json.dumps({
            "status": payload["status"],
            "generated_at": payload["generated_at"],
            "counts": payload["counts"],
            "heartbeat": str(HEARTBEAT_PATH),
        }, indent=2), flush=True)

        print(f"Sleeping {interval} seconds...", flush=True)
        time.sleep(interval)


def main() -> None:
    loop_mode = bool_env("RUNTIME_LOOP_FOREVER", False)

    if loop_mode:
        loop_forever()
    else:
        payload = run_once()
        print(json.dumps({
            "status": payload["status"],
            "generated_at": payload["generated_at"],
            "counts": payload["counts"],
            "status_path": str(STATUS_PATH),
            "heartbeat_path": str(HEARTBEAT_PATH),
        }, indent=2))


if __name__ == "__main__":
    main()
