from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


INPUTS = [
    Path("docs/data/prediction_engine/signal_dashboard_scored.json"),
    Path("docs/data/prediction_engine/signal_dashboard_market_guard_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_quality_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_news_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard.json"),
]

OUT_DASH = Path("docs/data/prediction_engine/signal_dashboard_second_leg_enriched.json")
OUT_SETUPS = Path("docs/data/prediction_engine/second_leg_setups.json")
OUT_STATE = Path("state/prediction_engine/second_leg_setups.json")
OUT_HEALTH = Path("docs/data/prediction_engine/second_leg_health.json")


class SecondLegState(str, Enum):
    NO_SETUP = "NO_SETUP"
    INITIAL_SPIKE = "INITIAL_SPIKE"
    PULLBACK_FORMING = "PULLBACK_FORMING"
    VWAP_HOLDING = "VWAP_HOLDING"
    VOLUME_CLEANSING = "VOLUME_CLEANSING"
    TRIGGER_ARMED = "TRIGGER_ARMED"
    SECOND_LEG_CONFIRMED = "SECOND_LEG_CONFIRMED"
    FAILED_SETUP = "FAILED_SETUP"


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


def load_rows() -> tuple[dict[str, Any], str]:
    for path in INPUTS:
        payload = read_json(path, {})
        rows = rows_from(payload)
        if rows:
            if not isinstance(payload, dict):
                payload = {"rows": rows}
            return payload, str(path)

    return {"rows": []}, "none"


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


def clamp(x: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, x))


def symbol(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def calculate_pullback_depth_pct(row: dict[str, Any]) -> float | None:
    price = f(pick(row, "price", "last_price", "close"))
    high = f(pick(row, "high_of_day", "hod", "day_high"))
    low = f(pick(row, "low_of_day", "lod", "day_low"))

    if price is None or high is None or low is None:
        return None

    leg_range = high - low
    if leg_range <= 0:
        return None

    return round((high - price) / leg_range * 100, 2)


def volume_cleansing_score(row: dict[str, Any]) -> float:
    volume_accel = f(pick(row, "volume_acceleration"), 1.0)
    rvol = f(pick(row, "time_slot_rvol", "relative_volume", "rvol"), 1.0)

    score = 50.0

    if rvol is not None and rvol >= 3:
        score += 20

    if volume_accel is not None:
        if 0.6 <= volume_accel <= 1.4:
            score += 25
        elif volume_accel < 0.6:
            score += 15
        elif volume_accel > 3:
            score -= 20

    return round(clamp(score), 2)


def micro_reclaim_score(row: dict[str, Any]) -> float:
    final_score = f(pick(row, "final_trade_score", "three_score_matrix.final_trade_score"), 0)
    entry_score = f(pick(row, "entry_quality_score", "three_score_matrix.entry_quality_score"), 0)
    day_move = f(pick(row, "day_move_percent", "day_change_pct", "day_change_percent"), 0)
    vwap_dist = f(pick(row, "vwap_distance_percent", "vwap_distance_pct"), None)

    score = 0.0

    if final_score is not None:
        score += clamp(final_score) * 0.35
    if entry_score is not None:
        score += clamp(entry_score) * 0.35
    if day_move is not None and day_move >= 5:
        score += 15
    if vwap_dist is not None and 0 <= vwap_dist <= 4:
        score += 15

    return round(clamp(score), 2)


def failed_or_current(
    state: SecondLegState,
    reasons: list[str],
    blocks: list[str],
    pullback_depth: float | None,
    cleanse: float,
    reclaim: float,
) -> dict[str, Any]:
    return {
        "state": state.value,
        "confirmed": False,
        "reasons": reasons,
        "blocks": blocks,
        "metrics": {
            "pullback_depth_pct": pullback_depth,
            "volume_cleansing_score": cleanse,
            "micro_reclaim_score": reclaim,
        },
    }


def classify_second_leg(row: dict[str, Any]) -> dict[str, Any]:
    day_move = f(pick(row, "day_move_percent", "day_change_pct", "day_change_percent"))
    rvol = f(pick(row, "time_slot_rvol", "relative_volume", "rvol"))
    vwap_dist = f(pick(row, "vwap_distance_percent", "vwap_distance_pct"))
    spread = f(pick(row, "advanced_quality.spread_pct", "spread_pct"))
    quote_age = f(pick(row, "quote_age_seconds", "quote_age", "age_seconds"))
    danger = f(pick(row, "danger_score", "three_score_matrix.danger_score"), 50)
    final_score = f(pick(row, "final_trade_score", "three_score_matrix.final_trade_score"), 0)
    score_status = str(pick(row, "score_status", "three_score_matrix.score_status") or "")

    pullback_depth = calculate_pullback_depth_pct(row)
    cleanse = volume_cleansing_score(row)
    reclaim = micro_reclaim_score(row)

    reasons: list[str] = []
    blocks: list[str] = []
    state = SecondLegState.NO_SETUP

    initial_spike = bool(
        day_move is not None
        and day_move >= 5
        and rvol is not None
        and rvol >= 2.5
    )

    if not initial_spike:
        blocks.append("no_initial_spike")
        return failed_or_current(state, reasons, blocks, pullback_depth, cleanse, reclaim)

    state = SecondLegState.INITIAL_SPIKE
    reasons.append("initial_spike_detected")

    if vwap_dist is None:
        blocks.append("missing_vwap_distance")
        return failed_or_current(state, reasons, blocks, pullback_depth, cleanse, reclaim)

    if vwap_dist < 0:
        blocks.append("below_vwap")
        return failed_or_current(SecondLegState.FAILED_SETUP, reasons, blocks, pullback_depth, cleanse, reclaim)

    if vwap_dist > 8:
        blocks.append("too_extended_from_vwap")
        return failed_or_current(SecondLegState.FAILED_SETUP, reasons, blocks, pullback_depth, cleanse, reclaim)

    state = SecondLegState.PULLBACK_FORMING
    reasons.append("pullback_or_consolidation_zone")

    if 0 <= vwap_dist <= 4:
        state = SecondLegState.VWAP_HOLDING
        reasons.append("vwap_holding")
    else:
        blocks.append("waiting_for_better_vwap_pullback")
        return failed_or_current(state, reasons, blocks, pullback_depth, cleanse, reclaim)

    if pullback_depth is not None and pullback_depth > 38.2:
        blocks.append("pullback_breached_38_2_retracement")
        return failed_or_current(SecondLegState.FAILED_SETUP, reasons, blocks, pullback_depth, cleanse, reclaim)

    if cleanse >= 70:
        state = SecondLegState.VOLUME_CLEANSING
        reasons.append("volume_cleansing_confirmed")
    else:
        blocks.append("volume_cleansing_not_confirmed")
        return failed_or_current(state, reasons, blocks, pullback_depth, cleanse, reclaim)

    if spread is not None and spread > 1.5:
        blocks.append("spread_too_wide")
    if quote_age is not None and quote_age > 2:
        blocks.append("quote_stale")
    if danger is not None and danger > 25:
        blocks.append("danger_score_too_high")

    if blocks:
        return failed_or_current(SecondLegState.FAILED_SETUP, reasons, blocks, pullback_depth, cleanse, reclaim)

    if reclaim >= 78 and final_score is not None and final_score >= 78:
        state = SecondLegState.TRIGGER_ARMED
        reasons.append("trigger_armed")

    if (
        reclaim >= 82
        and final_score is not None
        and final_score >= 82
        and score_status in {
            "TRADE_ELIGIBLE_SCORE_APPROVED",
            "WAIT_FOR_PULLBACK",
            "ALERT_ONLY",
        }
    ):
        state = SecondLegState.SECOND_LEG_CONFIRMED
        reasons.append("second_leg_confirmed")

    confirmed = state == SecondLegState.SECOND_LEG_CONFIRMED

    return {
        "state": state.value,
        "confirmed": confirmed,
        "reasons": reasons,
        "blocks": blocks,
        "metrics": {
            "pullback_depth_pct": pullback_depth,
            "volume_cleansing_score": cleanse,
            "micro_reclaim_score": reclaim,
            "vwap_distance_pct": vwap_dist,
            "spread_pct": spread,
            "quote_age_seconds": quote_age,
        },
    }


def enrich(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched = []

    for row in rows:
        second_leg = classify_second_leg(row)

        new = dict(row)
        new["second_leg"] = second_leg
        new["second_leg_state"] = second_leg["state"]
        new["second_leg_confirmed"] = second_leg["confirmed"]
        new["second_leg_blocks"] = second_leg["blocks"]
        new["second_leg_reasons"] = second_leg["reasons"]

        if second_leg["confirmed"]:
            new["setup_type"] = "SECOND_LEG_CONTINUATION"

        enriched.append(new)

    enriched.sort(
        key=lambda x: (
            1 if x.get("second_leg_confirmed") else 0,
            float(x.get("final_trade_score") or 0),
            float(x.get("runner_potential_score") or 0),
        ),
        reverse=True,
    )

    return enriched


def export() -> dict[str, Any]:
    dashboard, source = load_rows()
    rows = rows_from(dashboard)
    enriched = enrich(rows)
    generated_at = now()

    confirmed = [row for row in enriched if row.get("second_leg_confirmed")]

    dashboard["rows"] = enriched
    dashboard["schema_version"] = "signal_dashboard_second_leg_enriched_v1"
    dashboard["second_leg_generated_at"] = generated_at
    dashboard["second_leg_source"] = source

    setup_payload: dict[str, Any] = {
        "schema_version": "second_leg_setups_v1",
        "generated_at": generated_at,
        "status": "PASS",
        "source": source,
        "counts": {
            "rows": len(enriched),
            "second_leg_confirmed": len(confirmed),
            "not_confirmed": len(enriched) - len(confirmed),
        },
        "states": {},
        "setups": [
            {
                "ticker": symbol(row),
                "second_leg_state": row.get("second_leg_state"),
                "second_leg_confirmed": row.get("second_leg_confirmed"),
                "final_trade_score": row.get("final_trade_score"),
                "runner_potential_score": row.get("runner_potential_score"),
                "entry_quality_score": row.get("entry_quality_score"),
                "danger_score": row.get("danger_score"),
                "blocks": row.get("second_leg_blocks"),
                "reasons": row.get("second_leg_reasons"),
                "metrics": row.get("second_leg", {}).get("metrics", {}),
            }
            for row in enriched
        ],
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "purpose": "Second-leg structure classification only. Does not submit orders.",
            "disclaimer": "Research and paper-trading validation only. Not financial advice.",
        },
    }

    for row in enriched:
        state = row.get("second_leg_state") or "UNKNOWN"
        setup_payload["states"][state] = setup_payload["states"].get(state, 0) + 1

    health = {
        "schema_version": "second_leg_health_v1",
        "generated_at": generated_at,
        "status": "PASS",
        "rows": len(enriched),
        "second_leg_confirmed": len(confirmed),
        "states": setup_payload["states"],
        "order_submission": False,
        "live_trading": False,
    }

    write_json(OUT_DASH, dashboard)
    write_json(OUT_SETUPS, setup_payload)
    write_json(OUT_STATE, setup_payload)
    write_json(OUT_HEALTH, health)

    return {
        "status": "PASS",
        "rows": len(enriched),
        "second_leg_confirmed": len(confirmed),
        "dashboard_path": str(OUT_DASH),
        "setups_path": str(OUT_SETUPS),
        "health_path": str(OUT_HEALTH),
    }


def main() -> None:
    print(json.dumps(export(), indent=2))


if __name__ == "__main__":
    main()