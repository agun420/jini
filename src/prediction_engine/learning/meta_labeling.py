from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


INPUTS = [
    Path("docs/data/prediction_engine/signal_dashboard_rvol_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_second_leg_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_scored.json"),
    Path("docs/data/prediction_engine/signal_dashboard_quality_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard.json"),
]

WALK_FORWARD_PATH = Path("docs/data/prediction_engine/walk_forward_results.json")

OUT_PREDICTIONS = Path("docs/data/prediction_engine/meta_labeling_predictions.json")
OUT_HEALTH = Path("docs/data/prediction_engine/meta_labeling_health.json")
OUT_STATE = Path("state/prediction_engine/meta_labeling_predictions.json")


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


def rows_from(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]

    if isinstance(payload, dict):
        for key in ("rows", "signals", "candidates", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]

    return []


def load_rows() -> tuple[list[dict[str, Any]], str]:
    for path in INPUTS:
        payload = read_json(path, {})
        rows = rows_from(payload)
        if rows:
            return rows, str(path)

    return [], "none"


def nested(row: dict[str, Any], key: str) -> Any:
    cur: Any = row

    for part in key.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)

    return cur


def pick(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = nested(row, key) if "." in key else row.get(key)
        if value is not None:
            return value

    return None


def f(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def sigmoid(x: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def symbol(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def selected_walk_forward_params() -> dict[str, Any]:
    payload = read_json(WALK_FORWARD_PATH, {})
    if not isinstance(payload, dict):
        return {
            "name": "base_second_leg",
            "target_pct": 2.5,
            "stop_pct": 1.2,
        }

    best = payload.get("best_train_selection", {})
    params = best.get("params", {}) if isinstance(best, dict) else {}

    return {
        "name": params.get("name", "base_second_leg"),
        "target_pct": f(params.get("target_pct"), 2.5),
        "stop_pct": f(params.get("stop_pct"), 1.2),
    }


def feature_payload(row: dict[str, Any]) -> dict[str, float]:
    return {
        "runner_potential_score": f(
            pick(row, "runner_potential_score", "three_score_matrix.runner_potential_score"),
            50.0,
        ) or 50.0,
        "entry_quality_score": f(
            pick(row, "entry_quality_score", "three_score_matrix.entry_quality_score"),
            50.0,
        ) or 50.0,
        "danger_score": f(
            pick(row, "danger_score", "three_score_matrix.danger_score"),
            50.0,
        ) or 50.0,
        "final_trade_score": f(
            pick(row, "final_trade_score", "three_score_matrix.final_trade_score"),
            50.0,
        ) or 50.0,
        "time_slot_rvol": f(
            pick(row, "time_slot_rvol", "relative_volume", "rvol"),
            1.0,
        ) or 1.0,
        "vwap_distance_pct": f(
            pick(row, "vwap_distance_percent", "vwap_distance_pct"),
            8.0,
        ) or 8.0,
        "spread_pct": f(
            pick(row, "advanced_quality.spread_pct", "spread_pct"),
            1.5,
        ) or 1.5,
        "quote_age_seconds": f(
            pick(row, "quote_age_seconds", "quote_age", "age_seconds"),
            5.0,
        ) or 5.0,
        "second_leg_confirmed": 1.0 if row.get("second_leg_confirmed") is True else 0.0,
    }


def probability_success(features: dict[str, float]) -> float:
    """
    Lightweight meta-labeling proxy.

    This is intentionally not a trained ML model yet. It is a deterministic
    probability layer using the same features a future model will train on.
    Once enough labeled paper data exists, this module can be swapped for a
    fitted model.
    """

    runner = (features["runner_potential_score"] - 70.0) / 20.0
    entry = (features["entry_quality_score"] - 70.0) / 20.0
    final = (features["final_trade_score"] - 75.0) / 20.0
    danger = (25.0 - features["danger_score"]) / 25.0

    rvol = min(features["time_slot_rvol"], 8.0) / 8.0
    second_leg = features["second_leg_confirmed"]

    spread_penalty = max(0.0, features["spread_pct"] - 1.0) * 0.7
    quote_penalty = max(0.0, features["quote_age_seconds"] - 2.0) * 0.15
    vwap_penalty = 0.0

    if features["vwap_distance_pct"] < 0:
        vwap_penalty += 1.0
    elif features["vwap_distance_pct"] > 8:
        vwap_penalty += 0.8
    elif features["vwap_distance_pct"] > 4:
        vwap_penalty += 0.25

    raw = (
        runner * 0.95
        + entry * 1.10
        + final * 0.90
        + danger * 0.85
        + rvol * 0.35
        + second_leg * 0.65
        - spread_penalty
        - quote_penalty
        - vwap_penalty
        - 0.35
    )

    return round(sigmoid(raw) * 100.0, 2)


def model_decision(probability: float, row: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []

    danger = f(pick(row, "danger_score", "three_score_matrix.danger_score"), 50.0) or 50.0
    spread = f(pick(row, "advanced_quality.spread_pct", "spread_pct"), 1.5) or 1.5
    quote_age = f(pick(row, "quote_age_seconds", "quote_age", "age_seconds"), 5.0) or 5.0
    final_score = f(pick(row, "final_trade_score", "three_score_matrix.final_trade_score"), 0.0) or 0.0

    if danger > 40:
        reasons.append("danger_too_high")
    if spread > 1.5:
        reasons.append("spread_too_wide")
    if quote_age > 2:
        reasons.append("quote_stale")
    if final_score < 70:
        reasons.append("final_score_too_low")

    if reasons:
        return "MODEL_BLOCKED_BY_RISK", reasons

    if probability >= 70:
        return "MODEL_STRONG_WATCH", ["probability_over_70"]

    if probability >= 65:
        return "MODEL_WATCH", ["probability_over_65"]

    if probability >= 55:
        return "MODEL_WEAK_WATCH", ["probability_over_55"]

    return "MODEL_REJECT", ["probability_below_55"]


def export() -> dict[str, Any]:
    rows, source = load_rows()
    params = selected_walk_forward_params()
    generated_at = now()

    predictions = []

    for row in rows:
        features = feature_payload(row)
        probability = probability_success(features)
        decision, reasons = model_decision(probability, row)

        predictions.append({
            "ticker": symbol(row),
            "probability_target_before_stop_pct": probability,
            "model_decision": decision,
            "model_reasons": reasons,
            "selected_target_pct": params["target_pct"],
            "selected_stop_pct": params["stop_pct"],
            "selected_profile": params["name"],
            "features": features,
            "safety_note": "Research-only meta-label. Does not submit orders.",
        })

    predictions.sort(
        key=lambda x: x["probability_target_before_stop_pct"],
        reverse=True,
    )

    strong = [x for x in predictions if x["model_decision"] == "MODEL_STRONG_WATCH"]
    watch = [x for x in predictions if x["model_decision"] == "MODEL_WATCH"]

    output = {
        "schema_version": "meta_labeling_predictions_v1",
        "generated_at": generated_at,
        "status": "PASS",
        "mode": "research_only_probability_layer",
        "source": source,
        "walk_forward_params": params,
        "counts": {
            "rows": len(predictions),
            "strong_watch": len(strong),
            "watch": len(watch),
            "not_selected": len(predictions) - len(strong) - len(watch),
        },
        "thresholds": {
            "strong_watch_probability": 70,
            "watch_probability": 65,
            "weak_watch_probability": 55,
        },
        "predictions": predictions,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "model_can_override_risk_gate": False,
            "purpose": "Research-only meta-labeling. Does not submit orders.",
            "disclaimer": "Research and paper-trading validation only. Not financial advice.",
        },
    }

    health = {
        "schema_version": "meta_labeling_health_v1",
        "generated_at": generated_at,
        "status": "PASS",
        "rows": len(predictions),
        "strong_watch": len(strong),
        "watch": len(watch),
        "order_submission": False,
        "live_trading": False,
        "model_can_override_risk_gate": False,
    }

    write_json(OUT_PREDICTIONS, output)
    write_json(OUT_STATE, output)
    write_json(OUT_HEALTH, health)

    return {
        "status": "PASS",
        "rows": len(predictions),
        "strong_watch": len(strong),
        "watch": len(watch),
        "predictions_path": str(OUT_PREDICTIONS),
        "health_path": str(OUT_HEALTH),
    }


def main() -> None:
    print(json.dumps(export(), indent=2))


if __name__ == "__main__":
    main()