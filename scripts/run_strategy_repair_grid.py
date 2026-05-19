from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

OPERATOR_DASHBOARD = DOCS / "operator_dashboard.json"
TUNING_GRID = DOCS / "backtest_tuning_grid.json"

OUT_RESULTS = DOCS / "strategy_repair_grid.json"
OUT_HEALTH = DOCS / "strategy_repair_grid_health.json"
OUT_STATE = STATE / "strategy_repair_grid.json"


FINAL_THRESHOLDS = [40, 45, 50, 55, 60]
ENTRY_THRESHOLDS = [70, 75, 80, 85]
RUNNER_THRESHOLDS = [15, 20, 25, 30]
DANGER_MAX = [8, 10, 12, 15]
PRICE_MIN = [1, 3, 5]


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


def f(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        x = float(value)
        if math.isnan(x) or math.isinf(x):
            return None
        return x
    except Exception:
        return None


def ticker(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def price(row: dict[str, Any]) -> float | None:
    for key in ("price", "last_price", "close", "last", "mark"):
        x = f(row.get(key))
        if x is not None and x > 0:
            return x
    return None


def passes(row: dict[str, Any], cfg: dict[str, float]) -> bool:
    p = price(row)
    final = f(row.get("final_trade_score"))
    entry = f(row.get("entry_quality_score"))
    runner = f(row.get("runner_potential_score"))
    danger = f(row.get("danger_score"))

    if p is None or final is None or entry is None or runner is None or danger is None:
        return False

    return (
        p >= cfg["price_min"]
        and final >= cfg["final_min"]
        and entry >= cfg["entry_min"]
        and runner >= cfg["runner_min"]
        and danger <= cfg["danger_max"]
    )


def main() -> None:
    generated_at = now()

    operator = read_json(OPERATOR_DASHBOARD, {})
    tuning = read_json(TUNING_GRID, {})

    rows = rows_from(operator)
    all_results = tuning.get("all_results", []) if isinstance(tuning, dict) else []

    blockers: list[str] = []
    warnings: list[str] = []

    if not rows:
        blockers.append("operator_rows_missing")
    if not all_results:
        blockers.append("tuning_grid_results_missing")

    # We cannot fully backtest per-row filters from aggregate tuning results yet.
    # This package identifies filter strictness based on current signal pool quality
    # and pairs it with best parameter evidence from the tuning grid.
    best_combo = None
    if all_results:
        valid = [r for r in all_results if int(r.get("total_tests") or 0) >= 250]
        if valid:
            best_combo = sorted(
                valid,
                key=lambda r: (
                    float(r.get("profit_factor") or 0),
                    float(r.get("avg_return_pct") or -999),
                    float(r.get("selection_score") or -999),
                ),
                reverse=True,
            )[0]

    if not best_combo:
        blockers.append("best_combo_missing")

    repair_rows = []

    for final_min in FINAL_THRESHOLDS:
        for entry_min in ENTRY_THRESHOLDS:
            for runner_min in RUNNER_THRESHOLDS:
                for danger_max in DANGER_MAX:
                    for price_min in PRICE_MIN:
                        cfg = {
                            "final_min": final_min,
                            "entry_min": entry_min,
                            "runner_min": runner_min,
                            "danger_max": danger_max,
                            "price_min": price_min,
                        }

                        selected = [r for r in rows if passes(r, cfg)]
                        selected_tickers = [ticker(r) for r in selected if ticker(r)]

                        # Quality score is not a true backtest. It is a repair-priority score.
                        # We only promote filters that keep a small, cleaner pool.
                        avg_final = sum(f(r.get("final_trade_score")) or 0 for r in selected) / len(selected) if selected else 0
                        avg_entry = sum(f(r.get("entry_quality_score")) or 0 for r in selected) / len(selected) if selected else 0
                        avg_runner = sum(f(r.get("runner_potential_score")) or 0 for r in selected) / len(selected) if selected else 0
                        avg_danger = sum(f(r.get("danger_score")) or 0 for r in selected) / len(selected) if selected else 0

                        count = len(selected)

                        # Prefer stricter filters with some but not too many names.
                        count_penalty = abs(count - 5) * 2
                        repair_score = avg_final + (avg_entry * 0.35) + (avg_runner * 0.45) - (avg_danger * 1.2) - count_penalty

                        repair_rows.append({
                            **cfg,
                            "selected_count": count,
                            "selected_tickers": selected_tickers[:25],
                            "avg_final_trade_score": round(avg_final, 4),
                            "avg_entry_quality_score": round(avg_entry, 4),
                            "avg_runner_potential_score": round(avg_runner, 4),
                            "avg_danger_score": round(avg_danger, 4),
                            "repair_score": round(repair_score, 4),
                        })

    viable = [r for r in repair_rows if 1 <= int(r["selected_count"]) <= 10]
    top_filters = sorted(viable, key=lambda r: r["repair_score"], reverse=True)[:20]

    if not viable:
        warnings.append("no_viable_filter_with_1_to_10_candidates")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    recommended_filter = top_filters[0] if top_filters else None

    health = {
        "schema_version": "strategy_repair_grid_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "operator_rows": len(rows),
        "tested_filter_count": len(repair_rows),
        "viable_filter_count": len(viable),
        "recommended_filter": recommended_filter,
        "best_backtest_combo": best_combo,
        "backtest_gate_should_remain_active": True,
        "reason": "Tuning grid did not find profit_factor above 1.0, so filters are research-only until retested.",
        "order_submission": False,
        "live_trading": False,
    }

    payload = {
        "schema_version": "strategy_repair_grid_v1",
        "generated_at": generated_at,
        "status": status,
        "health": health,
        "top_filters": top_filters,
        "all_filters": repair_rows,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "purpose": "Research-only filter repair. Does not submit orders.",
        },
    }

    write_json(OUT_RESULTS, payload)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, payload)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
