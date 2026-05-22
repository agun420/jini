from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

PRE = DOCS / "v3_prebreakout_predictor.json"
REACTIVE = DOCS / "v3_research_alert_score.json"
PRE_JOURNAL = DOCS / "v3_prebreakout_outcome_journal.json"
REACTIVE_JOURNAL = DOCS / "v3_research_alert_outcome_journal.json"
REGIME = DOCS / "v3_market_regime_filter_health.json"

OUT_DOCS = DOCS / "v3_mathematical_edge_model.json"
OUT_HEALTH = DOCS / "v3_mathematical_edge_model_health.json"
OUT_STATE = STATE / "v3_mathematical_edge_model.json"

ESTIMATED_COST_PCT = 0.05
MAX_NOTIONAL = 2000.00
MIN_EDGE_EV_PCT = 0.03
MIN_EDGE_SCORE = 65.0

VALID_REASONS = {"TARGET_HIT", "STOP_HIT", "TIME_EXIT"}


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


def f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except Exception:
        return default


def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def sigmoid(x: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def ticker(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def list_rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = payload.get(key)
    if isinstance(rows, list):
        return [r for r in rows if isinstance(r, dict)]
    return []


def valid_closed(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("closed_alerts") or []
    return [
        r for r in rows
        if isinstance(r, dict)
        and r.get("exit_reason") in VALID_REASONS
        and r.get("return_pct") is not None
    ]


def journal_stats(payload: dict[str, Any]) -> dict[str, float]:
    rows = valid_closed(payload)
    if not rows:
        return {
            "closed": 0,
            "target_hit_rate": 0.50,
            "avg_return_pct": 0.0,
            "stop_hit_rate": 0.25,
            "time_exit_rate": 0.25,
        }

    targets = [r for r in rows if r.get("exit_reason") == "TARGET_HIT"]
    stops = [r for r in rows if r.get("exit_reason") == "STOP_HIT"]
    time_exits = [r for r in rows if r.get("exit_reason") == "TIME_EXIT"]
    returns = [f(r.get("return_pct")) for r in rows]

    return {
        "closed": len(rows),
        "target_hit_rate": len(targets) / len(rows),
        "avg_return_pct": sum(returns) / len(returns) if returns else 0.0,
        "stop_hit_rate": len(stops) / len(rows),
        "time_exit_rate": len(time_exits) / len(rows),
    }


def estimate_win_probability(row: dict[str, Any], layer: str, stats: dict[str, float], regime: str) -> float:
    """
    Blended probability estimate:
    - empirical base rate from journal
    - signal score
    - momentum/rvol/vwap/spread/quote quality
    - market regime adjustment
    """

    if layer == "PRE_BREAKOUT":
        score = f(row.get("prebreakout_score_v3"))
    else:
        score = f(row.get("research_alert_score_v3"))

    day_move = f(row.get("day_move_pct"))
    rvol = f(row.get("relative_volume"))
    vwap = f(row.get("vwap_distance_pct"))
    mom1 = f(row.get("momentum_1m"))
    mom5 = f(row.get("momentum_5m"))
    spread = f(row.get("spread_pct"), 0.02)
    quote_age = f(row.get("quote_age_sec"), 999)

    base = stats.get("target_hit_rate", 0.50)

    score_adj = (score - 65.0) / 100.0
    rvol_adj = min(max((rvol - 1.0) * 0.04, -0.04), 0.08)
    momentum_adj = min(max((mom1 + mom5) * 0.06, -0.05), 0.08)

    # Reward being above VWAP but not too stretched.
    if 0 <= vwap <= 2.0:
        vwap_adj = 0.04
    elif 2.0 < vwap <= 3.0:
        vwap_adj = -0.02
    elif vwap > 3.0:
        vwap_adj = -0.08
    else:
        vwap_adj = -0.03

    # Penalize poor execution quality.
    spread_adj = -0.04 if spread > 0.012 else 0.02
    quote_adj = -0.04 if quote_age > 60 else 0.02

    # Penalize late chase.
    if day_move >= 20:
        chase_adj = -0.12
    elif day_move >= 12:
        chase_adj = -0.06
    elif 2 <= day_move <= 8:
        chase_adj = 0.04
    else:
        chase_adj = 0.0

    if regime == "RISK_ON":
        regime_adj = 0.03
    elif regime == "RISK_OFF":
        regime_adj = -0.08
    else:
        regime_adj = 0.0

    p = base + score_adj + rvol_adj + momentum_adj + vwap_adj + spread_adj + quote_adj + chase_adj + regime_adj

    # Keep estimates conservative.
    return max(0.05, min(0.85, p))


def build_edge(row: dict[str, Any], layer: str, stats: dict[str, float], regime: str) -> dict[str, Any] | None:
    sym = ticker(row)
    price = f(row.get("live_price") or row.get("price"))

    if not sym or price <= 0:
        return None

    if layer == "PRE_BREAKOUT":
        status = row.get("prebreakout_status_v3")
        score = f(row.get("prebreakout_score_v3"))
        target = f(row.get("prebreakout_target_price"))
        stop = f(row.get("prebreakout_stop_price"))
        confidence = row.get("prebreakout_confidence")
        note = row.get("prebreakout_note")
        raw_target_pct = f(row.get("prebreakout_target_pct"), 0.35)
        raw_stop_pct = f(row.get("prebreakout_stop_pct"), 0.45)
    else:
        status = row.get("research_alert_status_v3")
        score = f(row.get("research_alert_score_v3"))
        target = f(row.get("research_target_price"))
        stop = f(row.get("research_stop_price"))
        confidence = row.get("research_confidence")
        note = row.get("research_confidence_note")
        raw_target_pct = f(row.get("research_target_pct"), 0.60)
        raw_stop_pct = f(row.get("research_stop_pct"), 0.80)

    target_pct = raw_target_pct if raw_target_pct > 0 else ((target - price) / price * 100 if target > price else 0.0)
    stop_pct = raw_stop_pct if raw_stop_pct > 0 else ((price - stop) / price * 100 if stop > 0 and stop < price else 0.0)

    if target_pct <= 0 or stop_pct <= 0:
        return None

    win_p = estimate_win_probability(row, layer, stats, regime)
    loss_p = 1 - win_p

    expected_value_pct = (win_p * target_pct) - (loss_p * stop_pct) - ESTIMATED_COST_PCT

    risk_reward = target_pct / stop_pct if stop_pct > 0 else 0.0
    expected_value_dollars = MAX_NOTIONAL * (expected_value_pct / 100.0)

    # Edge score blends EV, win probability, RR, signal score, and execution quality.
    spread = f(row.get("spread_pct"), 0.02)
    quote_age = f(row.get("quote_age_sec"), 999)

    execution_quality = 100.0
    if spread > 0.012:
        execution_quality -= 25
    if quote_age > 60:
        execution_quality -= 25
    execution_quality = clamp(execution_quality)

    ev_component = clamp((expected_value_pct + 0.25) * 160)
    win_component = clamp(win_p * 100)
    rr_component = clamp(risk_reward * 50)

    edge_score = (
        ev_component * 0.35
        + win_component * 0.25
        + rr_component * 0.15
        + clamp(score) * 0.15
        + execution_quality * 0.10
    )

    positive_edge = expected_value_pct >= MIN_EDGE_EV_PCT and edge_score >= MIN_EDGE_SCORE

    if positive_edge:
        edge_status = "POSITIVE_EDGE_REVIEW"
    elif expected_value_pct > 0:
        edge_status = "SMALL_EDGE_WATCH"
    else:
        edge_status = "NEGATIVE_EDGE_REJECT"

    planned_shares = int(MAX_NOTIONAL // price)
    planned_notional = planned_shares * price

    return {
        "ticker": sym,
        "layer": layer,
        "status": status,
        "confidence": confidence,
        "note": note,
        "live_price": round(price, 4),
        "target_price": round(target, 4),
        "stop_price": round(stop, 4),
        "target_pct": round(target_pct, 4),
        "stop_pct": round(stop_pct, 4),
        "risk_reward_ratio": round(risk_reward, 4),
        "estimated_win_probability": round(win_p, 4),
        "estimated_loss_probability": round(loss_p, 4),
        "estimated_cost_pct": ESTIMATED_COST_PCT,
        "expected_value_pct": round(expected_value_pct, 4),
        "expected_value_dollars": round(expected_value_dollars, 2),
        "edge_score": round(edge_score, 4),
        "edge_status": edge_status,
        "positive_edge": positive_edge,
        "signal_score": round(score, 4),
        "day_move_pct": row.get("day_move_pct"),
        "relative_volume": row.get("relative_volume"),
        "vwap_distance_pct": row.get("vwap_distance_pct"),
        "spread_pct": row.get("spread_pct"),
        "quote_age_sec": row.get("quote_age_sec"),
        "planned_shares": planned_shares,
        "planned_notional": round(planned_notional, 2),
        "paper_order_allowed": False,
        "order_submission": False,
        "live_trading": False,
    }


def main() -> None:
    generated_at = now_iso()

    pre = read_json(PRE, {})
    reactive = read_json(REACTIVE, {})
    pre_journal = read_json(PRE_JOURNAL, {})
    reactive_journal = read_json(REACTIVE_JOURNAL, {})
    regime_payload = read_json(REGIME, {})

    regime = str(regime_payload.get("regime") or "UNKNOWN").upper()

    pre_stats = journal_stats(pre_journal)
    reactive_stats = journal_stats(reactive_journal)

    blockers: list[str] = []
    warnings: list[str] = []

    if not pre:
        warnings.append("missing_prebreakout_predictor")
    if not reactive:
        warnings.append("missing_reactive_score")
    if regime == "UNKNOWN":
        warnings.append("market_regime_unknown")

    candidates: list[dict[str, Any]] = []

    for r in list_rows(pre, "candidates"):
        edge = build_edge(r, "PRE_BREAKOUT", pre_stats, regime)
        if edge:
            candidates.append(edge)

    for r in list_rows(reactive, "candidates"):
        edge = build_edge(r, "REACTIVE", reactive_stats, regime)
        if edge:
            candidates.append(edge)

    candidates.sort(key=lambda x: (x.get("positive_edge") is True, f(x.get("edge_score")), f(x.get("expected_value_pct"))), reverse=True)

    positive = [c for c in candidates if c.get("positive_edge") is True]
    small = [c for c in candidates if c.get("edge_status") == "SMALL_EDGE_WATCH"]
    rejected = [c for c in candidates if c.get("edge_status") == "NEGATIVE_EDGE_REJECT"]

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "v3_mathematical_edge_model_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "market_regime": regime,
        "candidate_count": len(candidates),
        "positive_edge_count": len(positive),
        "small_edge_watch_count": len(small),
        "negative_edge_reject_count": len(rejected),
        "top_ticker": candidates[0].get("ticker") if candidates else None,
        "top_edge_status": candidates[0].get("edge_status") if candidates else None,
        "top_expected_value_pct": candidates[0].get("expected_value_pct") if candidates else None,
        "top_edge_score": candidates[0].get("edge_score") if candidates else None,
        "estimated_cost_pct": ESTIMATED_COST_PCT,
        "max_notional": MAX_NOTIONAL,
        "paper_order_allowed": False,
        "order_submission": False,
        "live_trading": False,
    }

    out = {
        "schema_version": "v3_mathematical_edge_model_v1",
        "generated_at": generated_at,
        "health": health,
        "journal_stats": {
            "prebreakout": pre_stats,
            "reactive": reactive_stats,
        },
        "candidates": candidates,
        "positive_edge": positive,
        "small_edge_watch": small,
        "negative_edge_reject": rejected,
        "math": {
            "expected_value_formula": "EV% = P(win)*target_pct - (1-P(win))*stop_pct - estimated_cost_pct",
            "edge_score_formula": "Blend of EV component, win probability, risk/reward, signal score, execution quality",
            "estimated_cost_pct": ESTIMATED_COST_PCT,
            "min_edge_ev_pct": MIN_EDGE_EV_PCT,
            "min_edge_score": MIN_EDGE_SCORE,
        },
        "safety": {
            "purpose": "Mathematical edge model for research review only. Does not submit orders.",
            "paper_order_allowed": False,
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
