from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

STRICT_GATE = DOCS / "strict_trade_gate_v3.json"
STRICT_GATE_HEALTH = DOCS / "strict_trade_gate_v3_health.json"
FEED_STATUS = DOCS / "feed_status_health.json"
VALIDATION_STATUS = DOCS / "validation_status_health.json"
AUTO_READINESS = DOCS / "auto_trade_readiness_health.json"

OUT_DOCS = DOCS / "v3_signal_pipeline.json"
OUT_HEALTH = DOCS / "v3_signal_pipeline_health.json"
OUT_STATE = STATE / "v3_signal_pipeline.json"


SCRIPTS = [
    "scripts/run_top_gainer_opportunity_scanner.py",
    "scripts/run_feature_builder_snapshot.py",
    "scripts/run_runner_potential_v3.py",
    "scripts/run_entry_quality_v3.py",
    "scripts/run_danger_score_v3.py",
    "scripts/run_final_trade_score_v3.py",
    "scripts/run_strict_trade_gate_v3.py",
]


def now() -> str:
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


def rows_from(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "signals", "candidates", "items", "data", "predictions"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def run_script(script: str) -> dict[str, Any]:
    started_at = now()

    proc = subprocess.run(
        [sys.executable, script],
        text=True,
        capture_output=True,
        env={**dict(), **__import__("os").environ, "PYTHONPATH": "src:."},
    )

    return {
        "script": script,
        "started_at": started_at,
        "finished_at": now(),
        "returncode": proc.returncode,
        "ok": proc.returncode == 0,
        "stdout_tail": proc.stdout[-2000:],
        "stderr_tail": proc.stderr[-2000:],
    }


def main() -> None:
    generated_at = now()

    run_results = [run_script(script) for script in SCRIPTS]

    blockers: list[str] = []
    warnings: list[str] = []

    failed = [r for r in run_results if not r.get("ok")]
    if failed:
        blockers.append("one_or_more_v3_scripts_failed")

    gate_payload = read_json(STRICT_GATE, {})
    gate_health = read_json(STRICT_GATE_HEALTH, {})
    feed = read_json(FEED_STATUS, {})
    validation = read_json(VALIDATION_STATUS, {})
    readiness = read_json(AUTO_READINESS, {})

    rows = rows_from(gate_payload)

    ready_rows = [r for r in rows if r.get("buy_order_alert_eligible_v3") is True]
    blocked_rows = [r for r in rows if r.get("buy_order_alert_eligible_v3") is not True]

    if not rows:
        blockers.append("strict_trade_gate_v3_rows_missing")

    if gate_health.get("status") == "FAIL":
        blockers.append("strict_trade_gate_v3_failed")

    if feed.get("status") == "FAIL":
        blockers.append("feed_status_failed")

    if validation.get("validation_core_ready") is not True:
        warnings.append("validation_core_not_ready")

    if readiness.get("buy_order_alert_ready") is not True:
        warnings.append("legacy_buy_order_alert_not_ready")

    if not ready_rows:
        warnings.append("no_v3_buy_order_alert_rows_currently")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "v3_signal_pipeline_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "scripts_run": len(run_results),
        "scripts_failed": len(failed),
        "rows": len(rows),
        "v3_buy_order_alert_ready": len(ready_rows),
        "v3_buy_order_alert_blocked": len(blocked_rows),
        "top_ticker": rows[0].get("ticker") if rows else None,
        "top_gate": rows[0].get("trade_gate_status_v3") if rows else None,
        "top_final_trade_score_v3": rows[0].get("final_trade_score_v3") if rows else None,
        "feed_status": feed.get("status"),
        "feed_data_ready": feed.get("can_allow_buy_alerts_from_data"),
        "validation_core_ready": validation.get("validation_core_ready"),
        "buy_order_alert_ready": readiness.get("buy_order_alert_ready"),
        "paper_auto_trade_ready": False,
        "auto_trade_ready": False,
        "live_trade_ready": False,
        "trade_eligibility_enabled": False,
        "paper_order_allowed": False,
        "live_order_allowed": False,
        "order_submission": False,
        "live_trading": False,
    }

    payload = {
        "schema_version": "v3_signal_pipeline_v1",
        "generated_at": generated_at,
        "health": health,
        "run_results": run_results,
        "rows": rows,
        "ready_rows": ready_rows,
        "blocked_rows": blocked_rows,
        "safety": {
            "trade_eligibility_enabled": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
            "order_submission": False,
            "live_trading": False,
            "purpose": "Research-only v3 signal pipeline aggregator.",
        },
    }

    write_json(OUT_DOCS, payload)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, payload)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
