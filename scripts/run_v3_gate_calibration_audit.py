from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

PIPELINE = DOCS / "v3_signal_pipeline.json"

OUT_DOCS = DOCS / "v3_gate_calibration_audit.json"
OUT_HEALTH = DOCS / "v3_gate_calibration_audit_health.json"
OUT_STATE = STATE / "v3_gate_calibration_audit.json"


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
    if isinstance(payload, dict):
        rows = payload.get("rows")
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


def f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def pass_gate(row: dict[str, Any], gate: dict[str, float]) -> tuple[bool, list[str]]:
    blockers: list[str] = []

    price = f(row.get("price"))
    final = f(row.get("final_trade_score_v3"))
    runner = f(row.get("runner_potential_v3"))
    entry = f(row.get("entry_quality_v3"))
    danger = f(row.get("danger_score_v3"))
    spread = f(row.get("spread_pct"), -1)
    quote_age = f(row.get("quote_age_sec"), -1)
    day_move = f(row.get("day_move_pct"))
    rvol = f(row.get("relative_volume"))

    if price < gate["price_min"] or price > gate["price_max"]:
        blockers.append("outside_price_regime")

    if final < gate["min_final"]:
        blockers.append("final_below_gate")

    if runner < gate["min_runner"]:
        blockers.append("runner_below_gate")

    if entry < gate["min_entry"]:
        blockers.append("entry_below_gate")

    if danger > gate["max_danger"]:
        blockers.append("danger_above_gate")

    if spread < 0:
        blockers.append("spread_missing")
    elif spread > gate["max_spread"]:
        blockers.append("spread_too_wide")

    if quote_age < 0:
        blockers.append("quote_age_missing")
    elif quote_age > gate["max_quote_age"]:
        blockers.append("quote_stale")

    if day_move < gate["min_day_move"]:
        blockers.append("day_move_below_gate")

    if rvol < gate["min_rvol"]:
        blockers.append("rvol_below_gate")

    return len(blockers) == 0, blockers


def main() -> None:
    generated_at = now()
    payload = read_json(PIPELINE, {})
    rows = rows_from(payload)

    blockers: list[str] = []
    warnings: list[str] = []

    if not rows:
        blockers.append("no_v3_pipeline_rows")

    gates = {
        "current_strict": {
            "min_final": 70.0,
            "min_runner": 60.0,
            "min_entry": 55.0,
            "max_danger": 50.0,
            "price_min": 10.0,
            "price_max": 75.0,
            "max_spread": 0.025,
            "max_quote_age": 60.0,
            "min_day_move": -999.0,
            "min_rvol": 0.0,
        },
        "research_balanced": {
            "min_final": 50.0,
            "min_runner": 35.0,
            "min_entry": 45.0,
            "max_danger": 55.0,
            "price_min": 10.0,
            "price_max": 100.0,
            "max_spread": 0.025,
            "max_quote_age": 120.0,
            "min_day_move": 0.0,
            "min_rvol": 0.20,
        },
        "research_loose_watch": {
            "min_final": 45.0,
            "min_runner": 30.0,
            "min_entry": 40.0,
            "max_danger": 60.0,
            "price_min": 5.0,
            "price_max": 150.0,
            "max_spread": 0.03,
            "max_quote_age": 180.0,
            "min_day_move": -0.25,
            "min_rvol": 0.10,
        },
        "data_quality_only": {
            "min_final": 0.0,
            "min_runner": 0.0,
            "min_entry": 0.0,
            "max_danger": 100.0,
            "price_min": 1.0,
            "price_max": 500.0,
            "max_spread": 0.03,
            "max_quote_age": 180.0,
            "min_day_move": -999.0,
            "min_rvol": 0.0,
        },
    }

    results: dict[str, Any] = {}

    for gate_name, gate in gates.items():
        passed = []
        failed = []
        blocker_counts = Counter()

        for row in rows:
            ok, row_blockers = pass_gate(row, gate)
            if ok:
                passed.append(row)
            else:
                failed.append(row)
                for b in row_blockers:
                    blocker_counts[b] += 1

        results[gate_name] = {
            "gate": gate,
            "passed_count": len(passed),
            "failed_count": len(failed),
            "top_passed": [
                {
                    "ticker": r.get("ticker"),
                    "price": r.get("price"),
                    "final": r.get("final_trade_score_v3"),
                    "runner": r.get("runner_potential_v3"),
                    "entry": r.get("entry_quality_v3"),
                    "danger": r.get("danger_score_v3"),
                    "day_move": r.get("day_move_pct"),
                    "rvol": r.get("relative_volume"),
                    "spread": r.get("spread_pct"),
                    "quote_age": r.get("quote_age_sec"),
                }
                for r in passed[:20]
            ],
            "blocker_counts": dict(blocker_counts.most_common()),
        }

    if results.get("research_balanced", {}).get("passed_count", 0) == 0:
        warnings.append("research_balanced_gate_has_zero_passes")

    if results.get("data_quality_only", {}).get("passed_count", 0) == 0:
        warnings.append("data_quality_only_has_zero_passes_check_feed")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "v3_gate_calibration_audit_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "rows": len(rows),
        "current_strict_passed": results.get("current_strict", {}).get("passed_count", 0),
        "research_balanced_passed": results.get("research_balanced", {}).get("passed_count", 0),
        "research_loose_watch_passed": results.get("research_loose_watch", {}).get("passed_count", 0),
        "data_quality_only_passed": results.get("data_quality_only", {}).get("passed_count", 0),
        "active_gate_changed": False,
        "order_submission": False,
        "live_trading": False,
    }

    out = {
        "schema_version": "v3_gate_calibration_audit_v1",
        "generated_at": generated_at,
        "health": health,
        "results": results,
        "recommendation": {
            "message": "Research-only audit. Do not change active gate until forward outcomes validate the candidate threshold.",
            "active_gate_changed": False,
            "order_submission": False,
            "live_trading": False,
        },
    }

    write_json(OUT_DOCS, out)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, out)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
