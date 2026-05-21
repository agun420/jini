from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

ENRICHED = DOCS / "v3_enriched_rows.json"

OUT_DOCS = DOCS / "v3_prebreakout_predictor.json"
OUT_HEALTH = DOCS / "v3_prebreakout_predictor_health.json"
OUT_STATE = STATE / "v3_prebreakout_predictor.json"


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


def rows_from(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        rows = payload.get("rows")
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    return []


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


def ticker(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def score_row(row: dict[str, Any]) -> dict[str, Any]:
    sym = ticker(row)

    price = f(row.get("live_price") or row.get("price"))
    day_move = f(row.get("day_move_pct"))
    rvol = f(row.get("relative_volume"))
    spread = f(row.get("spread_pct"), -1.0)
    quote_age = f(row.get("quote_age_sec"), -1.0)
    vwap_dist = f(row.get("vwap_distance_pct"))
    mom1 = f(row.get("momentum_1m"))
    mom3 = f(row.get("momentum_3m"))
    mom5 = f(row.get("momentum_5m"))
    high_dist = f(row.get("high_of_day_distance_pct"), 999.0)
    intraday_range = f(row.get("intraday_range_pct"))
    dollar_volume = f(row.get("dollar_volume"))
    volume = f(row.get("volume"))

    final = f(row.get("final_trade_score_v3"))
    runner = f(row.get("runner_potential_v3"))
    entry = f(row.get("entry_quality_v3"))
    danger = f(row.get("danger_score_v3"))

    momentum_total = mom1 + mom3 + mom5

    blockers: list[str] = []
    warnings: list[str] = []

    if not sym:
        blockers.append("missing_ticker")
    if price <= 0:
        blockers.append("missing_price")
    if spread < 0:
        blockers.append("spread_missing")
    elif spread > 0.025:
        blockers.append("spread_too_wide")
    if quote_age < 0:
        blockers.append("quote_age_missing")
    elif quote_age > 120:
        blockers.append("quote_stale")
    if danger >= 70:
        blockers.append("danger_too_high")

    if price < 3:
        warnings.append("below_preferred_price")
    if price > 150:
        warnings.append("above_preferred_price")

    # No-chase / extension logic.
    highly_extended = day_move >= 20
    extended_above_vwap = day_move >= 12 and vwap_dist >= 2.5
    overheated = day_move >= 15 and rvol >= 1.0 and vwap_dist >= 2.0

    if highly_extended:
        warnings.append("highly_extended_day_move")
    if extended_above_vwap:
        warnings.append("extended_above_vwap")
    if overheated:
        warnings.append("overheated_momentum")

    # Pre-breakout conditions.
    # These are looking for pressure before the big candle.
    # Package 88: tighter early setup.
    # Old version allowed weak / negative setups that mostly timed out.
    compression_zone = (
        1.0 <= day_move <= 3.5
        and 1.0 <= rvol <= 4.0
        and 0.0 <= vwap_dist <= 1.50
        and mom1 >= 0.0
        and mom5 >= 0.05
        and momentum_total >= 0.10
        and 0 <= spread <= 0.010
        and 0 <= quote_age <= 45
        and danger <= 45
        and 3 <= price <= 100
    )

    vwap_reclaim_zone = (
        1.0 <= day_move <= 5.0
        and rvol >= 1.0
        and 0.0 <= vwap_dist <= 1.75
        and mom1 >= 0.0
        and mom5 >= 0.05
        and momentum_total >= 0.10
        and 0 <= spread <= 0.010
        and 0 <= quote_age <= 45
        and danger <= 45
        and 3 <= price <= 100
    )

    breakout_trigger_zone = (
        2.0 <= day_move <= 5.5
        and rvol >= 1.0
        and 0.0 <= vwap_dist <= 2.00
        and mom1 >= 0.0
        and mom5 >= 0.05
        and momentum_total >= 0.15
        and 0 <= spread <= 0.010
        and 0 <= quote_age <= 45
        and danger <= 45
        and 3 <= price <= 100
    )

    high_of_day_pressure = (
        high_dist <= 1.0
        and 2.0 <= day_move <= 5.5
        and rvol >= 1.0
        and 0.0 <= vwap_dist <= 2.00
        and mom1 >= 0.0
        and mom5 >= 0.05
        and momentum_total >= 0.15
        and danger <= 45
        and 0 <= spread <= 0.010
        and 0 <= quote_age <= 45
        and 3 <= price <= 100
    )

    pullback_reclaim_watch = (
        8.0 <= day_move <= 18.0
        and 0.0 <= vwap_dist <= 2.0
        and mom1 >= 0
        and mom5 >= -0.20
        and danger <= 50
        and 0 <= spread <= 0.012
        and 0 <= quote_age <= 60
        and 3 <= price <= 100
    )

    # Score components.
    quality_base = 0.0
    quality_base += clamp(final, 0, 70) * 0.16
    quality_base += clamp(runner, 0, 70) * 0.18
    quality_base += clamp(entry, 0, 80) * 0.18
    quality_base += clamp(70 - danger, 0, 70) * 0.12

    compression_bonus = 18.0 if compression_zone else 0.0
    reclaim_bonus = 16.0 if vwap_reclaim_zone else 0.0
    trigger_bonus = 18.0 if breakout_trigger_zone else 0.0
    hod_bonus = 14.0 if high_of_day_pressure else 0.0
    pullback_bonus = 8.0 if pullback_reclaim_watch else 0.0

    # Controlled move gets rewarded. Huge move gets punished.
    if -1 <= day_move <= 3:
        move_bonus = 8.0
    elif 3 < day_move <= 8:
        move_bonus = 10.0
    elif 8 < day_move <= 12:
        move_bonus = 3.0
    elif day_move > 12:
        move_bonus = -10.0
    else:
        move_bonus = 0.0

    # Volume acceleration proxy: current field is recent ratio, not true 20-day RVOL.
    if 0.35 <= rvol <= 1.5:
        volume_bonus = 10.0
    elif 1.5 < rvol <= 3.5:
        volume_bonus = 8.0
    elif rvol > 3.5:
        volume_bonus = 4.0
    else:
        volume_bonus = 0.0

    momentum_bonus = clamp(momentum_total, 0, 3) * 4.0

    if -0.50 <= vwap_dist <= 1.25:
        vwap_bonus = 10.0
    elif 1.25 < vwap_dist <= 2.25:
        vwap_bonus = 4.0
    elif vwap_dist > 2.25:
        vwap_bonus = -8.0
    else:
        vwap_bonus = 0.0

    execution_bonus = 0.0
    if 0 <= spread <= 0.006:
        execution_bonus += 6.0
    elif 0 <= spread <= 0.012:
        execution_bonus += 3.0
    if 0 <= quote_age <= 15:
        execution_bonus += 6.0
    elif 15 < quote_age <= 60:
        execution_bonus += 3.0

    liquidity_bonus = 0.0
    if dollar_volume >= 1_000_000:
        liquidity_bonus = 5.0
    elif volume >= 100_000:
        liquidity_bonus = 3.0

    chase_penalty = 0.0
    if highly_extended:
        chase_penalty += 28.0
    if extended_above_vwap:
        chase_penalty += 18.0
    if overheated:
        chase_penalty += 12.0

    prebreakout_score = (
        quality_base
        + compression_bonus
        + reclaim_bonus
        + trigger_bonus
        + hod_bonus
        + pullback_bonus
        + move_bonus
        + volume_bonus
        + momentum_bonus
        + vwap_bonus
        + execution_bonus
        + liquidity_bonus
        - chase_penalty
    )
    prebreakout_score = clamp(prebreakout_score)

    # Final status.
    if blockers:
        status = "BLOCKED"
    elif highly_extended:
        status = "CHASE_RISK_EXTENDED"
    elif extended_above_vwap or overheated:
        status = "WAIT_FOR_PULLBACK"
    elif prebreakout_score >= 80 and (breakout_trigger_zone or high_of_day_pressure):
        status = "BREAKOUT_TRIGGER_CANDIDATE"
    elif prebreakout_score >= 76 and (compression_zone or vwap_reclaim_zone):
        status = "PRE_BREAKOUT_CANDIDATE"
    elif pullback_reclaim_watch and prebreakout_score >= 58:
        status = "PULLBACK_RECLAIM_WATCH"
    elif prebreakout_score >= 52:
        status = "WATCH"
    else:
        status = "TRACK_ONLY"

    is_candidate = status in {"PRE_BREAKOUT_CANDIDATE", "BREAKOUT_TRIGGER_CANDIDATE"}

    target_pct = 0.60
    stop_pct = 0.80
    target_price = price * (1 + target_pct / 100) if price > 0 else 0
    stop_price = price * (1 - stop_pct / 100) if price > 0 else 0

    if status == "PRE_BREAKOUT_CANDIDATE":
        confidence = "HIGH PRE-BREAKOUT"
        note = "Pre-breakout candidate. Not extended. Near VWAP with early volume/momentum pressure."
    elif status == "BREAKOUT_TRIGGER_CANDIDATE":
        confidence = "HIGH BREAKOUT"
        note = "Breakout trigger candidate. Momentum is active but still inside no-chase limits."
    elif status == "PULLBACK_RECLAIM_WATCH":
        confidence = "PULLBACK WATCH"
        note = "Extended but controlled. Wait for pullback/reclaim before treating as actionable."
    elif status == "WAIT_FOR_PULLBACK":
        confidence = "WAIT"
        note = "Too extended above VWAP. Do not chase. Wait for reset/reclaim."
    elif status == "CHASE_RISK_EXTENDED":
        confidence = "CHASE RISK"
        note = "Already highly extended today. Runner watch only, not a clean candidate."
    elif status == "WATCH":
        confidence = "WATCH"
        note = "Some setup ingredients are present, but it is not a pre-breakout candidate yet."
    elif status == "BLOCKED":
        confidence = "BLOCKED"
        note = "Blocked by hard data/safety rules."
    else:
        confidence = "LOW"
        note = "Track only."

    out = dict(row)
    out.update(
        {
            "prebreakout_score_v3": round(prebreakout_score, 4),
            "prebreakout_status_v3": status,
            "prebreakout_candidate_v3": is_candidate,
            "live_price": round(price, 4),
            "prebreakout_target_pct": target_pct,
            "prebreakout_stop_pct": stop_pct,
            "prebreakout_target_price": round(target_price, 4),
            "prebreakout_stop_price": round(stop_price, 4),
            "prebreakout_confidence": confidence,
            "prebreakout_note": note,
            "prebreakout_blockers_v3": blockers,
            "prebreakout_warnings_v3": warnings,
            "prebreakout_features_v3": {
                "compression_zone": compression_zone,
                "vwap_reclaim_zone": vwap_reclaim_zone,
                "breakout_trigger_zone": breakout_trigger_zone,
                "high_of_day_pressure": high_of_day_pressure,
                "pullback_reclaim_watch": pullback_reclaim_watch,
                "highly_extended": highly_extended,
                "extended_above_vwap": extended_above_vwap,
                "overheated": overheated,
                "momentum_total": round(momentum_total, 4),
                "quality_base": round(quality_base, 4),
                "compression_bonus": compression_bonus,
                "reclaim_bonus": reclaim_bonus,
                "trigger_bonus": trigger_bonus,
                "hod_bonus": hod_bonus,
                "pullback_bonus": pullback_bonus,
                "move_bonus": move_bonus,
                "volume_bonus": volume_bonus,
                "vwap_bonus": vwap_bonus,
                "execution_bonus": execution_bonus,
                "liquidity_bonus": liquidity_bonus,
                "chase_penalty": chase_penalty,
            },
            "order_submission": False,
            "live_trading": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
        }
    )
    return out


def main() -> None:
    generated_at = now_iso()
    payload = read_json(ENRICHED, {})
    rows = rows_from(payload)

    blockers: list[str] = []
    warnings: list[str] = []

    if not rows:
        blockers.append("no_enriched_rows")

    scored = [score_row(r) for r in rows]
    scored.sort(
        key=lambda r: (
            r.get("prebreakout_candidate_v3") is True,
            f(r.get("prebreakout_score_v3")),
            f(r.get("day_move_pct")),
        ),
        reverse=True,
    )

    candidates = [r for r in scored if r.get("prebreakout_candidate_v3") is True]
    pre = [r for r in scored if r.get("prebreakout_status_v3") == "PRE_BREAKOUT_CANDIDATE"]
    trigger = [r for r in scored if r.get("prebreakout_status_v3") == "BREAKOUT_TRIGGER_CANDIDATE"]
    pullback = [r for r in scored if r.get("prebreakout_status_v3") == "PULLBACK_RECLAIM_WATCH"]
    wait = [r for r in scored if r.get("prebreakout_status_v3") == "WAIT_FOR_PULLBACK"]
    chase = [r for r in scored if r.get("prebreakout_status_v3") == "CHASE_RISK_EXTENDED"]
    watch = [r for r in scored if r.get("prebreakout_status_v3") == "WATCH"]
    blocked = [r for r in scored if r.get("prebreakout_status_v3") == "BLOCKED"]

    if not candidates:
        warnings.append("no_prebreakout_candidates_currently")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "v3_prebreakout_predictor_health_v2_tightened",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "rows": len(scored),
        "prebreakout_candidates": len(pre),
        "breakout_trigger_candidates": len(trigger),
        "total_candidates": len(candidates),
        "pullback_reclaim_watch": len(pullback),
        "wait_for_pullback": len(wait),
        "chase_risk_extended": len(chase),
        "watch": len(watch),
        "blocked": len(blocked),
        "top_ticker": scored[0].get("ticker") if scored else None,
        "top_status": scored[0].get("prebreakout_status_v3") if scored else None,
        "top_score": scored[0].get("prebreakout_score_v3") if scored else None,
        "order_submission": False,
        "live_trading": False,
        "paper_order_allowed": False,
        "live_order_allowed": False,
    }

    out = {
        "schema_version": "v3_prebreakout_predictor_v2_tightened",
        "generated_at": generated_at,
        "health": health,
        "rows": scored,
        "candidates": candidates,
        "prebreakout_candidates": pre,
        "breakout_trigger_candidates": trigger,
        "pullback_reclaim_watch": pullback,
        "wait_for_pullback": wait,
        "chase_risk_extended": chase,
        "safety": {
            "purpose": "Pre-breakout predictor and no-chase guard. Does not trade.",
            "order_submission": False,
            "live_trading": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
        },
    }

    write_json(OUT_DOCS, out)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, out)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
