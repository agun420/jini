from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

PIPELINE = DOCS / "v3_signal_pipeline.json"

OUT_DOCS = DOCS / "v3_research_alert_score.json"
OUT_HEALTH = DOCS / "v3_research_alert_score_health.json"
OUT_STATE = STATE / "v3_research_alert_score.json"


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
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except Exception:
        return default


def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def score_row(row: dict[str, Any]) -> dict[str, Any]:
    price = f(row.get("price"))
    final = f(row.get("final_trade_score_v3"))
    runner = f(row.get("runner_potential_v3"))
    entry = f(row.get("entry_quality_v3"))
    danger = f(row.get("danger_score_v3"))
    day_move = f(row.get("day_move_pct"))
    rvol = f(row.get("relative_volume"))
    spread = f(row.get("spread_pct"), -1)
    quote_age = f(row.get("quote_age_sec"), -1)
    vwap_dist = f(row.get("vwap_distance_pct"))
    mom1 = f(row.get("momentum_1m"))
    mom3 = f(row.get("momentum_3m"))
    mom5 = f(row.get("momentum_5m"))

    blockers: list[str] = []
    warnings: list[str] = []

    # Data quality hard blocks only.
    if price <= 0:
        blockers.append("missing_price")

    if spread < 0:
        blockers.append("spread_missing")
    elif spread > 0.03:
        blockers.append("spread_too_wide")

    if quote_age < 0:
        blockers.append("quote_age_missing")
    elif quote_age > 180:
        blockers.append("quote_stale")

    # Research alert price range. Wider than strict gate, but still avoids extreme names.
    if price < 3 or price > 250:
        warnings.append("outside_preferred_research_price_range")

    if danger > 65:
        blockers.append("danger_too_high_for_research_alert")

    if day_move < -1:
        warnings.append("negative_day_move")

    if rvol < 0.10:
        warnings.append("low_recent_volume_ratio")

    if vwap_dist < -3:
        warnings.append("weak_below_vwap")

    momentum_total = mom1 + mom3 + mom5

    # Research alert score. This is separate from final_trade_score_v3.
    # It rewards actionable watch strength, not auto-trade readiness.
    base = 0.0
    base += clamp(final, 0, 70) * 0.25
    base += clamp(runner, 0, 70) * 0.25
    base += clamp(entry, 0, 80) * 0.25
    base += clamp(70 - danger, 0, 70) * 0.10

    # Market action boosters.
    day_move_bonus = clamp(day_move, 0, 10) * 1.2
    rvol_bonus = clamp(rvol, 0, 5) * 3.0
    momentum_bonus = clamp(momentum_total, 0, 5) * 2.0

    # Clean data / execution quality bonus.
    spread_bonus = 5.0 if 0 <= spread <= 0.01 else 2.0
    quote_bonus = 5.0 if 0 <= quote_age <= 30 else 2.0

    score = base + day_move_bonus + rvol_bonus + momentum_bonus + spread_bonus + quote_bonus
    score = clamp(score)

    # Research candidate gate v2.
    # This is alert-only. It does not place orders.
    candidate_ready = (
        score >= 60
        and not blockers
        and day_move >= 3
        and danger <= 45
        and 0 <= spread <= 0.012
        and 0 <= quote_age <= 60
        and price >= 3
        and price <= 100
    )

    if blockers:
        status = "RESEARCH_BLOCKED"
    elif candidate_ready:
        status = "RESEARCH_BUY_ALERT_CANDIDATE"
    elif score >= 52:
        status = "RESEARCH_WATCH"
    else:
        status = "RESEARCH_TRACK_ONLY"

    out = dict(row)
    out.update(
        {
            "research_alert_score_v3": round(score, 4),
            "research_alert_status_v3": status,
            "research_alert_candidate_v3": status == "RESEARCH_BUY_ALERT_CANDIDATE",
            "research_alert_blockers_v3": blockers,
            "research_alert_warnings_v3": warnings,
            "research_alert_components_v3": {
                "base_from_existing_scores": round(base, 4),
                "day_move_bonus": round(day_move_bonus, 4),
                "rvol_bonus": round(rvol_bonus, 4),
                "momentum_bonus": round(momentum_bonus, 4),
                "spread_bonus": round(spread_bonus, 4),
                "quote_bonus": round(quote_bonus, 4),
            },
            "paper_order_allowed": False,
            "live_order_allowed": False,
            "order_submission": False,
            "live_trading": False,
        }
    )
    return out


def main() -> None:
    generated_at = now()
    payload = read_json(PIPELINE, {})
    rows = rows_from(payload)

    blockers: list[str] = []
    warnings: list[str] = []

    if not rows:
        blockers.append("no_v3_pipeline_rows")

    scored = [score_row(r) for r in rows]
    scored.sort(
        key=lambda r: (
            r.get("research_alert_candidate_v3") is True,
            f(r.get("research_alert_score_v3")),
            f(r.get("final_trade_score_v3")),
        ),
        reverse=True,
    )

    candidates = [r for r in scored if r.get("research_alert_status_v3") == "RESEARCH_BUY_ALERT_CANDIDATE"]
    watch = [r for r in scored if r.get("research_alert_status_v3") == "RESEARCH_WATCH"]
    track = [r for r in scored if r.get("research_alert_status_v3") == "RESEARCH_TRACK_ONLY"]
    blocked = [r for r in scored if r.get("research_alert_status_v3") == "RESEARCH_BLOCKED"]

    if not candidates:
        warnings.append("no_research_buy_alert_candidates_currently")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "v3_research_alert_score_health_v2",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "rows": len(scored),
        "research_buy_alert_candidates": len(candidates),
        "research_watch": len(watch),
        "research_track_only": len(track),
        "research_blocked": len(blocked),
        "top_ticker": scored[0].get("ticker") if scored else None,
        "top_research_alert_score_v3": scored[0].get("research_alert_score_v3") if scored else None,
        "active_strict_gate_changed": False,
        "paper_order_allowed": False,
        "live_order_allowed": False,
        "order_submission": False,
        "live_trading": False,
    }

    out = {
        "schema_version": "v3_research_alert_score_v2",
        "generated_at": generated_at,
        "health": health,
        "rows": scored,
        "candidates": candidates,
        "watch": watch,
        "safety": {
            "purpose": "Research-only V3 alert candidate layer. Does not trade.",
            "active_strict_gate_changed": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
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
