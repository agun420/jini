from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

EXT_RESULTS = DOCS / "pullback_reclaim_extended_validation.json"
SCORE_V2_DASH = DOCS / "signal_dashboard_score_v2.json"

OUT_RESULTS = DOCS / "regime_split_validation.json"
OUT_HEALTH = DOCS / "regime_split_validation_health.json"
OUT_STATE = STATE / "regime_split_validation.json"


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
        for key in ("rows", "signals", "candidates", "items", "data", "predictions", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        x = float(value)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except Exception:
        return default


def ticker(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or row.get("symbol") or "").upper().strip()


def build_symbol_meta() -> dict[str, dict[str, Any]]:
    dash = read_json(SCORE_V2_DASH, {})
    out = {}

    for row in rows_from(dash):
        sym = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
        if not sym:
            continue
        out[sym] = {
            "price": f(row.get("price") or row.get("last_price") or row.get("close")),
            "score_v2": f(row.get("score_v2")),
            "runner": f(row.get("runner_potential_score")),
            "rvol": f(row.get("time_slot_rvol"), 1.0),
            "danger": f(row.get("danger_score")),
        }

    return out


def bucket_price(price: float) -> str:
    if price < 3:
        return "price_lt_3"
    if price < 10:
        return "price_3_to_10"
    if price < 75:
        return "price_10_to_75"
    return "price_75_plus"


def bucket_score(score: float) -> str:
    if score >= 55:
        return "score_v2_55_plus"
    if score >= 45:
        return "score_v2_45_to_55"
    if score >= 35:
        return "score_v2_35_to_45"
    return "score_v2_lt_35"


def bucket_rvol(rvol: float) -> str:
    if rvol >= 1.5:
        return "rvol_1_5_plus"
    if rvol >= 1.0:
        return "rvol_1_0_to_1_5"
    return "rvol_lt_1"


def bucket_runner(runner: float) -> str:
    if runner >= 25:
        return "runner_25_plus"
    if runner >= 15:
        return "runner_15_to_25"
    return "runner_lt_15"


def symbol_result_to_sample(result: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    tests = int(result.get("tests") or 0)
    wins = int(result.get("wins") or 0)
    losses = int(result.get("losses") or 0)
    flats = int(result.get("flats") or 0)
    avg_return = f(result.get("avg_return_pct"))
    symbol = str(result.get("symbol") or "").upper()

    return {
        "symbol": symbol,
        "tests": tests,
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "avg_return_pct": avg_return,
        "price": f(meta.get("price")),
        "score_v2": f(meta.get("score_v2")),
        "rvol": f(meta.get("rvol"), 1.0),
        "runner": f(meta.get("runner")),
        "danger": f(meta.get("danger")),
    }


def summarize_group(name: str, samples: list[dict[str, Any]], target_pct: float, stop_pct: float) -> dict[str, Any]:
    tests = sum(int(s.get("tests") or 0) for s in samples)
    wins = sum(int(s.get("wins") or 0) for s in samples)
    losses = sum(int(s.get("losses") or 0) for s in samples)
    flats = sum(int(s.get("flats") or 0) for s in samples)

    avg_return = (
        sum(f(s.get("avg_return_pct")) * int(s.get("tests") or 0) for s in samples) / tests
        if tests else 0
    )

    pf = (wins * target_pct) / (losses * stop_pct) if losses else (999 if wins else 0)

    return {
        "group": name,
        "symbols": [s["symbol"] for s in samples],
        "symbols_count": len(samples),
        "total_tests": tests,
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "target_hit_rate_pct": round((wins / tests) * 100, 2) if tests else 0,
        "stop_hit_rate_pct": round((losses / tests) * 100, 2) if tests else 0,
        "avg_return_pct": round(avg_return, 5),
        "profit_factor": round(pf, 5),
        "passes_research_gate": tests >= 100 and pf >= 1.2 and avg_return > 0,
    }


def main() -> None:
    generated_at = now()

    ext = read_json(EXT_RESULTS, {})
    meta = build_symbol_meta()

    target_pct = f(ext.get("target_pct"), 0.6)
    stop_pct = f(ext.get("stop_pct"), 0.8)

    results = rows_from(ext)
    samples = []

    blockers: list[str] = []
    warnings: list[str] = []

    if not results:
        blockers.append("extended_validation_results_missing")

    for r in results:
        if r.get("status") != "PASS":
            continue
        sym = str(r.get("symbol") or "").upper()
        samples.append(symbol_result_to_sample(r, meta.get(sym, {})))

    if not samples:
        blockers.append("no_symbol_samples")

    groups: dict[str, list[dict[str, Any]]] = {}

    def add_group(name: str, sample: dict[str, Any]) -> None:
        groups.setdefault(name, []).append(sample)

    for s in samples:
        add_group(bucket_price(f(s.get("price"))), s)
        add_group(bucket_score(f(s.get("score_v2"))), s)
        add_group(bucket_rvol(f(s.get("rvol"), 1.0)), s)
        add_group(bucket_runner(f(s.get("runner"))), s)

        if f(s.get("price")) >= 10 and f(s.get("score_v2")) >= 45:
            add_group("combo_price_10_plus_score_45_plus", s)

        if f(s.get("price")) >= 10 and f(s.get("rvol"), 1.0) >= 1.0:
            add_group("combo_price_10_plus_rvol_1_plus", s)

        if f(s.get("score_v2")) >= 45 and f(s.get("rvol"), 1.0) >= 1.0:
            add_group("combo_score_45_plus_rvol_1_plus", s)

        if f(s.get("price")) >= 10 and f(s.get("score_v2")) >= 45 and f(s.get("rvol"), 1.0) >= 1.0:
            add_group("combo_price_10_score_45_rvol_1", s)

    summaries = [summarize_group(name, vals, target_pct, stop_pct) for name, vals in groups.items()]
    summaries.sort(key=lambda x: (x["passes_research_gate"], x["profit_factor"], x["avg_return_pct"], x["total_tests"]), reverse=True)

    passing = [x for x in summaries if x.get("passes_research_gate")]

    if not passing:
        warnings.append("no_regime_passed_research_gate")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "regime_split_validation_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "sample_symbols": len(samples),
        "group_count": len(summaries),
        "passing_group_count": len(passing),
        "best_group": summaries[0] if summaries else None,
        "order_submission": False,
        "live_trading": False,
    }

    payload = {
        "schema_version": "regime_split_validation_v1",
        "generated_at": generated_at,
        "status": status,
        "health": health,
        "target_pct": target_pct,
        "stop_pct": stop_pct,
        "samples": samples,
        "groups": summaries,
        "passing_groups": passing,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "purpose": "Research-only regime split validation. Does not submit orders.",
        },
    }

    write_json(OUT_RESULTS, payload)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, payload)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
