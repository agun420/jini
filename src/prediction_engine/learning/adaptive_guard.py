from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


OUTCOMES_PATH = Path("docs/data/prediction_engine/outcomes.json")
SIGNAL_DASHBOARD_CANDIDATES = [
    Path("docs/data/prediction_engine/signal_dashboard_market_guard_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_quality_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_news_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_finra_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard.json"),
]
LEARNING_PATH = Path("docs/data/prediction_engine/learning.json")

ADAPTIVE_STATE_PATH = Path("state/prediction_engine/adaptive_guard_state.json")
ADAPTIVE_DOCS_PATH = Path("docs/data/prediction_engine/adaptive_guard.json")
ADAPTIVE_HEALTH_PATH = Path("docs/data/prediction_engine/adaptive_guard_health.json")


BASE_MIN_SCORE = 85.0
BASE_MIN_ML_PROBABILITY = 0.70
BASE_MAX_NOTIONAL = 2000.0

LOSS_LABELS = {"STOP_BEFORE_TARGET"}
WIN_LABELS = {"TARGET_BEFORE_STOP"}
NEUTRAL_LABELS = {"TIME_EXPIRED", "PRICE_ONLY", "PENDING", "NO_BAR_DATA", "NO_PRICE_DATA", "UNLABELABLE"}


def now_utc_iso() -> str:
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
    path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def extract_rows(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        for key in ("rows", "signals", "history", "events", "items", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

    return []


def load_signal_rows() -> Tuple[List[Dict[str, Any]], str]:
    for path in SIGNAL_DASHBOARD_CANDIDATES:
        payload = read_json(path, {})
        rows = extract_rows(payload)
        if rows:
            return rows, str(path)
    return [], "none"


def latest_final_label(outcome_row: Dict[str, Any]) -> str:
    """
    Prefer the longest completed horizon.
    If all horizons are pending/no data, return the last known label.
    """
    outcomes = outcome_row.get("outcomes")
    if not isinstance(outcomes, list) or not outcomes:
        return "UNKNOWN"

    completed = [
        item for item in outcomes
        if isinstance(item, dict) and item.get("label") not in {"PENDING"}
    ]

    if completed:
        return str(completed[-1].get("label") or "UNKNOWN")

    return str(outcomes[-1].get("label") or "UNKNOWN")


def close_return_for_row(outcome_row: Dict[str, Any]) -> Optional[float]:
    outcomes = outcome_row.get("outcomes")
    if not isinstance(outcomes, list):
        return None

    for item in reversed(outcomes):
        if not isinstance(item, dict):
            continue
        value = safe_float(item.get("close_return_pct"))
        if value is not None:
            return value

    return None


def summarize_outcomes(outcome_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    labels: List[str] = []
    returns: List[float] = []

    for row in outcome_rows:
        label = latest_final_label(row)
        labels.append(label)

        ret = close_return_for_row(row)
        if ret is not None:
            returns.append(ret)

    wins = sum(1 for label in labels if label in WIN_LABELS)
    losses = sum(1 for label in labels if label in LOSS_LABELS)
    usable = wins + losses

    win_rate = wins / usable if usable else None
    avg_return = sum(returns) / len(returns) if returns else None

    recent_5 = labels[-5:]
    recent_10 = labels[-10:]
    recent_losses_5 = sum(1 for label in recent_5 if label in LOSS_LABELS)
    recent_losses_10 = sum(1 for label in recent_10 if label in LOSS_LABELS)

    return {
        "total_outcome_rows": len(outcome_rows),
        "usable_win_loss_rows": usable,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 4) if win_rate is not None else None,
        "average_close_return_pct": round(avg_return, 4) if avg_return is not None else None,
        "recent_5_labels": recent_5,
        "recent_10_labels": recent_10,
        "recent_losses_5": recent_losses_5,
        "recent_losses_10": recent_losses_10,
        "label_counts": {label: labels.count(label) for label in sorted(set(labels))},
        "return_observation_count": len(returns),
    }


def summarize_current_signals(signal_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    statuses: Dict[str, int] = {}
    scores: List[float] = []

    for row in signal_rows:
        status = str(row.get("status") or row.get("signal") or "UNKNOWN")
        statuses[status] = statuses.get(status, 0) + 1

        score = safe_float(row.get("score"))
        if score is not None:
            scores.append(score)

    return {
        "total_signals": len(signal_rows),
        "status_counts": statuses,
        "trade_eligible_count": statuses.get("TRADE_ELIGIBLE", 0),
        "average_score": round(sum(scores) / len(scores), 4) if scores else None,
        "max_score": max(scores) if scores else None,
    }


def classify_guard_state(outcome_summary: Dict[str, Any], signal_summary: Dict[str, Any]) -> Dict[str, Any]:
    reasons: List[str] = []

    min_score = BASE_MIN_SCORE
    min_ml_probability = BASE_MIN_ML_PROBABILITY
    max_notional = BASE_MAX_NOTIONAL

    allow_new_entries = True
    risk_mode = "NORMAL"

    recent_losses_5 = int(outcome_summary.get("recent_losses_5") or 0)
    recent_losses_10 = int(outcome_summary.get("recent_losses_10") or 0)
    win_rate = outcome_summary.get("win_rate")
    usable = int(outcome_summary.get("usable_win_loss_rows") or 0)
    avg_return = outcome_summary.get("average_close_return_pct")

    if recent_losses_5 >= 5:
        allow_new_entries = False
        risk_mode = "PAUSED"
        reasons.append("last_5_completed_outcomes_are_losses")
    elif recent_losses_5 >= 3:
        risk_mode = "DEFENSIVE"
        min_score += 5
        min_ml_probability += 0.05
        max_notional = min(max_notional, 1000.0)
        reasons.append("3_or_more_losses_in_last_5_completed_outcomes")
    elif recent_losses_10 >= 4:
        risk_mode = "CAUTION"
        min_score += 3
        min_ml_probability += 0.03
        max_notional = min(max_notional, 1500.0)
        reasons.append("4_or_more_losses_in_last_10_completed_outcomes")

    if usable >= 10 and win_rate is not None and win_rate < 0.45:
        risk_mode = "DEFENSIVE" if risk_mode != "PAUSED" else risk_mode
        min_score = max(min_score, BASE_MIN_SCORE + 5)
        min_ml_probability = max(min_ml_probability, BASE_MIN_ML_PROBABILITY + 0.05)
        max_notional = min(max_notional, 1000.0)
        reasons.append("win_rate_below_45_percent_after_10_or_more_usable_outcomes")

    if avg_return is not None and outcome_summary.get("return_observation_count", 0) >= 10 and avg_return < -0.5:
        risk_mode = "DEFENSIVE" if risk_mode != "PAUSED" else risk_mode
        min_score = max(min_score, BASE_MIN_SCORE + 5)
        max_notional = min(max_notional, 1000.0)
        reasons.append("average_close_return_below_negative_0_5_percent")

    if signal_summary.get("trade_eligible_count", 0) == 0:
        reasons.append("no_current_trade_eligible_signals")

    if not reasons:
        reasons.append("normal_risk_mode")

    return {
        "allow_new_entries": allow_new_entries,
        "risk_mode": risk_mode,
        "min_score_required": round(min_score, 2),
        "min_ml_probability_required": round(min_ml_probability, 4),
        "max_notional_per_trade": round(max_notional, 2),
        "base_max_notional_per_trade": BASE_MAX_NOTIONAL,
        "reasons": reasons,
        "hard_blocks": [
            "live_trading_disabled",
            "short_selling_disabled",
            "options_disabled",
            "only_trade_eligible_can_reach_future_paper_gate",
        ],
        "blocked_statuses": [
            "WAIT_FOR_PULLBACK",
            "ALERT_ONLY",
            "WATCH_ONLY",
            "NO_TRADE",
        ],
    }


def build_adaptive_guard() -> Dict[str, Any]:
    outcome_payload = read_json(OUTCOMES_PATH, {})
    outcome_rows = extract_rows(outcome_payload)

    signal_rows, signal_source = load_signal_rows()

    outcome_summary = summarize_outcomes(outcome_rows)
    signal_summary = summarize_current_signals(signal_rows)
    guard = classify_guard_state(outcome_summary, signal_summary)

    payload = {
        "schema_version": "adaptive_guard_v1",
        "generated_at": now_utc_iso(),
        "status": "PASS",
        "mode": "paper_only_research",
        "outcome_source": str(OUTCOMES_PATH),
        "signal_source": signal_source,
        "guard": guard,
        "outcome_summary": outcome_summary,
        "signal_summary": signal_summary,
        "explainability": {
            "what_this_does": [
                "Reads outcome labels and current signals.",
                "Recommends defensive thresholds.",
                "Writes a guard state for future paper execution.",
            ],
            "what_this_does_not_do": [
                "Does not place orders.",
                "Does not modify broker settings.",
                "Does not change code automatically.",
                "Does not enable live trading.",
            ],
        },
        "safety": {
            "paper_only": True,
            "order_submission": False,
            "live_trading": False,
            "changes_thresholds_directly": False,
            "recommended_for_future_gate_only": True,
            "disclaimer": "Adaptive guard is a research safety layer. Not financial advice.",
        },
    }

    return payload


def export_adaptive_guard() -> Dict[str, Any]:
    payload = build_adaptive_guard()

    health = {
        "schema_version": "adaptive_guard_health_v1",
        "generated_at": payload["generated_at"],
        "status": payload["status"],
        "risk_mode": payload["guard"]["risk_mode"],
        "allow_new_entries": payload["guard"]["allow_new_entries"],
        "min_score_required": payload["guard"]["min_score_required"],
        "max_notional_per_trade": payload["guard"]["max_notional_per_trade"],
        "outcome_rows": payload["outcome_summary"]["total_outcome_rows"],
        "current_signals": payload["signal_summary"]["total_signals"],
        "order_submission": False,
        "paper_only": True,
        "notes": [
            "Package 6 creates a defensive adaptive guard state.",
            "It does not trade and does not directly change any execution settings.",
            "Future paper execution packages should read this file before any order plan.",
        ],
    }

    write_json(ADAPTIVE_STATE_PATH, payload)
    write_json(ADAPTIVE_DOCS_PATH, payload)
    write_json(ADAPTIVE_HEALTH_PATH, health)

    return {
        "status": "PASS",
        "risk_mode": payload["guard"]["risk_mode"],
        "allow_new_entries": payload["guard"]["allow_new_entries"],
        "output_state": str(ADAPTIVE_STATE_PATH),
        "output_docs": str(ADAPTIVE_DOCS_PATH),
        "health_path": str(ADAPTIVE_HEALTH_PATH),
    }


def main() -> None:
    print(json.dumps(export_adaptive_guard(), indent=2))


if __name__ == "__main__":
    main()
