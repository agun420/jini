from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

OUT_DOCS = DOCS / "v3_tomorrow_morning_command_pack.json"
OUT_HEALTH = DOCS / "v3_tomorrow_morning_command_pack_health.json"
OUT_STATE = STATE / "v3_tomorrow_morning_command_pack.json"


COMMANDS = [
    "scripts/run_alpaca_v3_market_enrichment.py",
    "scripts/run_v3_market_regime_filter.py",
    "scripts/run_v3_prebreakout_predictor.py",
    "scripts/run_v3_research_alert_score.py",
    "scripts/run_v3_mathematical_edge_model.py",
    "scripts/run_v3_paper_plan_export.py",
    "scripts/run_v3_package_100_validation.py",
    "scripts/run_v3_morning_readiness_report.py",
]


READ_FILES = {
    "package_100": DOCS / "v3_package_100_validation_health.json",
    "morning": DOCS / "v3_morning_readiness_report_health.json",
    "paper_plan": DOCS / "v3_paper_order_plan_health.json",
    "edge": DOCS / "v3_mathematical_edge_model_health.json",
    "regime": DOCS / "v3_market_regime_filter_health.json",
    "morning_report": DOCS / "v3_morning_readiness_report.json",
}


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


def run_cmd(script: str) -> dict[str, Any]:
    cmd = ["python", script]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            text=True,
            capture_output=True,
            timeout=180,
        )
        return {
            "script": script,
            "returncode": proc.returncode,
            "ok": proc.returncode == 0,
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        }
    except Exception as exc:
        return {
            "script": script,
            "returncode": -1,
            "ok": False,
            "error": str(exc),
        }


def main() -> None:
    generated_at = now_iso()

    results = [run_cmd(script) for script in COMMANDS]

    blockers: list[str] = []
    warnings: list[str] = []

    for r in results:
        if not r.get("ok"):
            # Package 100 may exit 1 when validation fails, and that should still be reported.
            blockers.append("script_failed_" + str(r.get("script")).replace("/", "_"))

    package_100 = read_json(READ_FILES["package_100"], {})
    morning = read_json(READ_FILES["morning"], {})
    paper_plan = read_json(READ_FILES["paper_plan"], {})
    edge = read_json(READ_FILES["edge"], {})
    regime = read_json(READ_FILES["regime"], {})
    morning_report = read_json(READ_FILES["morning_report"], {})

    if package_100.get("status") != "PASS":
        blockers.append("package_100_not_pass")

    if paper_plan.get("order_submission") is not False:
        blockers.append("paper_plan_order_submission_not_false")

    if paper_plan.get("live_trading") is not False:
        blockers.append("paper_plan_live_trading_not_false")

    if edge.get("order_submission") is not False:
        blockers.append("edge_model_order_submission_not_false")

    if edge.get("live_trading") is not False:
        blockers.append("edge_model_live_trading_not_false")

    if morning.get("order_submission") is not False:
        blockers.append("morning_order_submission_not_false")

    if morning.get("live_trading") is not False:
        blockers.append("morning_live_trading_not_false")

    if regime.get("regime") == "RISK_OFF":
        warnings.append("market_regime_risk_off_review_only")

    if not morning_report.get("locked_watchlist"):
        warnings.append("no_locked_watchlist_currently")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    locked = morning_report.get("locked_watchlist", [])
    locked_slim = []
    if isinstance(locked, list):
        for p in locked[:10]:
            if isinstance(p, dict):
                locked_slim.append({
                    "ticker": p.get("ticker"),
                    "layer": p.get("layer"),
                    "edge_status": p.get("edge_status"),
                    "edge_score": p.get("edge_score"),
                    "expected_value_pct": p.get("expected_value_pct"),
                    "estimated_win_probability": p.get("estimated_win_probability"),
                    "risk_reward_ratio": p.get("risk_reward_ratio"),
                    "live_price": p.get("live_price"),
                    "planned_shares": p.get("planned_shares"),
                    "planned_notional": p.get("planned_notional"),
                    "target_price": p.get("target_price"),
                    "stop_price": p.get("stop_price"),
                    "order_submission": p.get("order_submission"),
                    "live_trading": p.get("live_trading"),
                })

    health = {
        "schema_version": "v3_tomorrow_morning_command_pack_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "scripts_run": len(results),
        "scripts_failed": len([r for r in results if not r.get("ok")]),
        "package_100_status": package_100.get("status"),
        "package_100_score": package_100.get("score"),
        "morning_readiness": morning.get("readiness"),
        "market_regime": regime.get("regime"),
        "market_regime_score": regime.get("regime_score"),
        "positive_edge_count": edge.get("positive_edge_count"),
        "paper_plan_count": paper_plan.get("plan_count"),
        "locked_watchlist_count": len(locked_slim),
        "paper_trade_ready": False,
        "paper_order_allowed": False,
        "order_submission": False,
        "live_trading": False,
    }

    out = {
        "schema_version": "v3_tomorrow_morning_command_pack_v1",
        "generated_at": generated_at,
        "health": health,
        "script_results": results,
        "locked_watchlist": locked_slim,
        "summary": {
            "readiness": morning.get("readiness"),
            "package_100_score": package_100.get("score"),
            "market_regime": regime.get("regime"),
            "paper_plan_count": paper_plan.get("plan_count"),
            "positive_edge_count": edge.get("positive_edge_count"),
            "instruction": "Review only. Do not enable order submission. Do not enable live trading.",
        },
        "safety": {
            "research_only": True,
            "paper_plan_only": True,
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
