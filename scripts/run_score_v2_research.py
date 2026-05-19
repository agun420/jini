from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

OPERATOR_DASHBOARD = DOCS / "operator_dashboard.json"
SCORING_AUDIT = DOCS / "scoring_formula_audit_health.json"

OUT_DASH = DOCS / "signal_dashboard_score_v2.json"
OUT_HEALTH = DOCS / "score_v2_research_health.json"
OUT_STATE = STATE / "score_v2_research.json"


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


def price(row: dict[str, Any]) -> float:
    for key in ("price", "last_price", "close", "last", "mark"):
        x = f(row.get(key), 0.0)
        if x > 0:
            return x
    return 0.0


def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def price_quality(p: float) -> float:
    # Audit showed higher price bucket had better edge than low-price bucket.
    # Keep it simple: avoid penny/near-penny noise. Do not over-reward mega caps.
    if p <= 0:
        return 0
    if p < 1:
        return 5
    if p < 3:
        return 25
    if p < 10:
        return 55
    if p < 75:
        return 80
    if p < 250:
        return 70
    return 55


def rvol_quality(v: float) -> float:
    # Small positive edge. Reward moderate/high RVOL, not extreme blindly.
    if v <= 0:
        return 35
    if v < 0.8:
        return 30
    if v < 1.2:
        return 50
    if v < 2.5:
        return 70
    if v < 5:
        return 75
    return 60


def runner_quality(v: float) -> float:
    # Runner had some positive edge, so keep it, but cap it.
    return clamp(v * 2.2, 0, 85)


def danger_penalty(v: float) -> float:
    # Danger was harmful in audit; penalize more strongly.
    return clamp(v * 2.8, 0, 50)


def score_v2(row: dict[str, Any]) -> dict[str, Any]:
    p = price(row)
    runner = f(row.get("runner_potential_score"))
    rvol = f(row.get("time_slot_rvol"), 1.0)
    danger = f(row.get("danger_score"))

    pq = price_quality(p)
    rq = runner_quality(runner)
    rvq = rvol_quality(rvol)
    dp = danger_penalty(danger)

    # Do not use old final_trade_score or entry_quality_score as positive drivers.
    raw = (
        pq * 0.40
        + rq * 0.30
        + rvq * 0.20
        + 10.0
        - dp * 0.45
    )

    score = clamp(raw, 0, 100)

    if p <= 0:
        status = "DATA_FEED_FAIL"
    elif score >= 70:
        status = "SCORE_V2_STRONG_WATCH"
    elif score >= 55:
        status = "SCORE_V2_WATCH"
    else:
        status = "SCORE_V2_TRACK_ONLY"

    return {
        "score_v2": round(score, 4),
        "score_v2_status": status,
        "score_v2_components": {
            "price_quality": round(pq, 4),
            "runner_quality": round(rq, 4),
            "rvol_quality": round(rvq, 4),
            "danger_penalty": round(dp, 4),
        },
    }


def main() -> None:
    generated_at = now()

    operator = read_json(OPERATOR_DASHBOARD, {})
    audit = read_json(SCORING_AUDIT, {})

    rows = rows_from(operator)

    blockers: list[str] = []
    warnings: list[str] = []

    if not rows:
        blockers.append("operator_rows_missing")

    out_rows = []
    strong_watch = 0
    watch = 0
    track_only = 0

    for row in rows:
        new = dict(row)
        sv2 = score_v2(new)
        new.update(sv2)

        # Research only. Never make trade eligible.
        new["score_v2_trade_eligible"] = False
        new["alert_eligible"] = False
        new["paper_order_allowed"] = False
        new["live_order_allowed"] = False
        new["order_submission"] = False
        new["live_trading"] = False

        status = new.get("score_v2_status")
        if status == "SCORE_V2_STRONG_WATCH":
            strong_watch += 1
        elif status == "SCORE_V2_WATCH":
            watch += 1
        else:
            track_only += 1

        out_rows.append(new)

    out_rows.sort(key=lambda r: f(r.get("score_v2")), reverse=True)

    if strong_watch == 0:
        warnings.append("no_score_v2_strong_watch_rows")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "score_v2_research_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "rows": len(out_rows),
        "strong_watch": strong_watch,
        "watch": watch,
        "track_only": track_only,
        "scoring_audit_status": audit.get("status"),
        "old_score_trusted": False,
        "entry_quality_trusted": False,
        "trade_eligibility_enabled": False,
        "order_submission": False,
        "live_trading": False,
        "message": "Score v2 is research-only. It does not enable buy alerts or order submission.",
    }

    payload = {
        "schema_version": "signal_dashboard_score_v2_research_v1",
        "generated_at": generated_at,
        "status": status,
        "health": health,
        "rows": out_rows,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "purpose": "Research-only score v2 candidate.",
        },
    }

    write_json(OUT_DASH, payload)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, payload)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
