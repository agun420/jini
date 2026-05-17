from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


INPUTS = [
    Path("docs/data/prediction_engine/signal_dashboard_market_guard_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_quality_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_news_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_finra_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard.json"),
    Path("docs/data/prediction_engine/alpaca_paid_market_candidates.json"),
]

OUT_DASH = Path("docs/data/prediction_engine/signal_dashboard_scored.json")
OUT_MATRIX = Path("docs/data/prediction_engine/three_score_matrix.json")
OUT_STATE = Path("state/prediction_engine/three_score_matrix.json")
OUT_HEALTH = Path("docs/data/prediction_engine/three_score_matrix_health.json")


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


def norm(value: float | None, lo: float, hi: float, invert: bool = False) -> float:
    if value is None:
        return 50.0
    score = clamp((value - lo) / (hi - lo) * 100)
    return 100 - score if invert else score


def symbol(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def runner_score(row: dict[str, Any]) -> tuple[float, list[str]]:
    rvol = f(pick(row, "time_slot_rvol", "relative_volume", "rvol"))
    day = f(pick(row, "day_move_percent", "day_change_pct", "day_change_percent"))
    gap = f(pick(row, "gap_percent", "gap_pct"))
    accel = f(pick(row, "volume_acceleration"))
    news = f(pick(row, "catalyst_score", "news_score", "alpaca_news.catalyst_score"), 0)
    base = f(pick(row, "score", "runner_score"), 0)

    score = (
        norm(rvol, 1, 6) * 0.25
        + norm(day, 0, 35) * 0.22
        + norm(gap, 0, 20) * 0.10
        + norm(accel, 0.5, 3) * 0.18
        + clamp(news or 0) * 0.13
        + clamp(base or 0) * 0.12
    )

    reasons = []
    if rvol is not None and rvol >= 3:
        reasons.append("strong_rvol")
    if day is not None and day >= 5:
        reasons.append("positive_day_move")
    if accel is not None and accel >= 1.25:
        reasons.append("volume_acceleration")
    if news and news >= 60:
        reasons.append("strong_catalyst")

    return round(clamp(score), 2), reasons


def entry_score(row: dict[str, Any]) -> tuple[float, list[str]]:
    vwap = f(pick(row, "vwap_distance_percent", "vwap_distance_pct"))
    spread = f(pick(row, "advanced_quality.spread_pct", "spread_pct"))
    age = f(pick(row, "quote_age_seconds", "quote_age", "age_seconds"))
    pullback = f(pick(row, "advanced_quality.pullback_quality_score", "pullback_quality_score"))
    breakout = f(pick(row, "advanced_quality.breakout_compression_score", "breakout_compression_score"))
    quality = f(pick(row, "advanced_quality.advanced_quality_score", "advanced_quality_score"), 50)

    if vwap is None:
        vwap_score = 45
    elif 0 <= vwap <= 4:
        vwap_score = 100
    elif 4 < vwap <= 6:
        vwap_score = 70
    elif vwap < 0:
        vwap_score = 20
    else:
        vwap_score = 25

    score = (
        vwap_score * 0.25
        + norm(spread, 0, 1.5, True) * 0.17
        + norm(age, 0, 2, True) * 0.17
        + norm(pullback, 0, 18) * 0.14
        + norm(breakout, 0, 20) * 0.10
        + clamp(quality or 50) * 0.17
    )

    reasons = []
    if vwap is not None and 0 <= vwap <= 4:
        reasons.append("clean_vwap_zone")
    if spread is not None and spread <= 1:
        reasons.append("spread_clean")
    if age is not None and age <= 2:
        reasons.append("quote_fresh")

    return round(clamp(score), 2), reasons


def danger_score(row: dict[str, Any]) -> tuple[float, list[str], list[str]]:
    day = f(pick(row, "day_move_percent", "day_change_pct", "day_change_percent"))
    vwap = f(pick(row, "vwap_distance_percent", "vwap_distance_pct"))
    spread = f(pick(row, "advanced_quality.spread_pct", "spread_pct"))
    age = f(pick(row, "quote_age_seconds", "quote_age", "age_seconds"))
    halt = f(pick(row, "advanced_quality.halt_risk_score", "market_guard.halt_luld_proxy_score"), 0)

    score = (
        norm(day, 35, 120) * 0.22
        + norm(vwap, 6, 15) * 0.22
        + norm(spread, 0.75, 2) * 0.18
        + norm(age, 2, 10) * 0.18
        + clamp(halt or 0) * 0.20
    )

    reasons = []
    blocks = []

    if day is not None and day >= 100:
        reasons.append("parabolic_day_move")
        blocks.append("day_move_over_100")
    if vwap is not None and vwap >= 10:
        reasons.append("vwap_extension_high")
        blocks.append("vwap_extension_over_10")
    if spread is not None and spread > 1.5:
        reasons.append("spread_too_wide")
        blocks.append("spread_over_1_5")
    if age is not None and age > 2:
        reasons.append("quote_stale")
        blocks.append("quote_age_over_2")
    if halt and halt >= 60:
        reasons.append("halt_risk_high")
        blocks.append("halt_risk_high")

    toxic = pick(row, "toxic_risk", "sec_toxic_risk", "dilution_risk")
    if toxic is True or str(toxic).upper() in {"TRUE", "HIGH", "BLOCK"}:
        reasons.append("toxic_risk")
        blocks.append("toxic_risk")
        score = 100

    return round(clamp(score), 2), reasons, sorted(set(blocks))


def market_score(row: dict[str, Any]) -> float:
    regime = str(
        pick(
            row,
            "advanced_quality.market_regime",
            "market_regime",
            "market_circuit_proxy.market_circuit_proxy_status",
        )
        or "NEUTRAL"
    ).upper()

    if regime in {"NORMAL", "RISK_ON"}:
        return 80
    if regime in {"RISK_OFF", "MARKET_STRESS", "LEVEL_1_PROXY", "LEVEL_2_PROXY", "LEVEL_3_PROXY"}:
        return 20
    return 50


def status_for(
    runner: float,
    entry: float,
    danger: float,
    final: float,
    blocks: list[str],
) -> tuple[str, list[str]]:
    reasons = list(blocks)

    if runner < 80:
        reasons.append("runner_potential_below_80")
    if entry < 78:
        reasons.append("entry_quality_below_78")
    if danger > 25:
        reasons.append("danger_score_above_25")
    if final < 82:
        reasons.append("final_trade_score_below_82")

    if not reasons:
        return "TRADE_ELIGIBLE_SCORE_APPROVED", []

    if runner >= 75 and entry >= 65 and danger <= 40:
        return "WAIT_FOR_PULLBACK", reasons

    if runner >= 65:
        return "ALERT_ONLY", reasons

    return "WATCH_ONLY", reasons


def enrich(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []

    for row in rows:
        runner, runner_reasons = runner_score(row)
        entry, entry_reasons = entry_score(row)
        danger, danger_reasons, hard_blocks = danger_score(row)
        market = market_score(row)

        final = round(
            clamp(
                runner * 0.40
                + entry * 0.40
                + market * 0.10
                - danger * 0.10
            ),
            2,
        )

        score_status, score_blocks = status_for(
            runner,
            entry,
            danger,
            final,
            hard_blocks,
        )

        new = dict(row)
        new["runner_potential_score"] = runner
        new["entry_quality_score"] = entry
        new["danger_score"] = danger
        new["market_regime_score"] = market
        new["final_trade_score"] = final
        new["score_status"] = score_status
        new["score_blocks"] = score_blocks
        new["three_score_matrix"] = {
            "runner_potential_score": runner,
            "entry_quality_score": entry,
            "danger_score": danger,
            "market_regime_score": market,
            "final_trade_score": final,
            "score_status": score_status,
            "score_blocks": score_blocks,
            "reason_codes": {
                "runner": runner_reasons,
                "entry": entry_reasons,
                "danger": danger_reasons,
            },
        }
        out.append(new)

    out.sort(
        key=lambda x: (
            x.get("final_trade_score") or 0,
            x.get("runner_potential_score") or 0,
        ),
        reverse=True,
    )

    return out


def export() -> dict[str, Any]:
    dashboard, source = load_rows()
    rows = rows_from(dashboard)
    scored = enrich(rows)
    generated_at = now()

    dashboard["rows"] = scored
    dashboard["schema_version"] = "signal_dashboard_scored_v1"
    dashboard["three_score_source"] = source
    dashboard["three_score_generated_at"] = generated_at

    approved = sum(
        1
        for row in scored
        if row.get("score_status") == "TRADE_ELIGIBLE_SCORE_APPROVED"
    )

    matrix = {
        "schema_version": "three_score_matrix_v1",
        "generated_at": generated_at,
        "status": "PASS",
        "source": source,
        "counts": {
            "rows": len(scored),
            "score_approved": approved,
            "not_approved": len(scored) - approved,
        },
        "thresholds": {
            "runner_potential_min": 80,
            "entry_quality_min": 78,
            "danger_score_max": 25,
            "final_trade_score_min": 82,
        },
        "weights": {
            "runner_potential_score": 0.40,
            "entry_quality_score": 0.40,
            "market_regime_score": 0.10,
            "danger_score": -0.10,
        },
        "rows": [
            {
                "ticker": symbol(row),
                "runner_potential_score": row.get("runner_potential_score"),
                "entry_quality_score": row.get("entry_quality_score"),
                "danger_score": row.get("danger_score"),
                "final_trade_score": row.get("final_trade_score"),
                "score_status": row.get("score_status"),
                "score_blocks": row.get("score_blocks"),
            }
            for row in scored
        ],
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "purpose": "Scoring only. Does not submit orders.",
            "disclaimer": "Research and paper-trading validation only. Not financial advice.",
        },
    }

    health = {
        "schema_version": "three_score_matrix_health_v1",
        "generated_at": generated_at,
        "status": "PASS",
        "rows": len(scored),
        "score_approved": approved,
        "order_submission": False,
        "live_trading": False,
    }

    write_json(OUT_DASH, dashboard)
    write_json(OUT_MATRIX, matrix)
    write_json(OUT_STATE, matrix)
    write_json(OUT_HEALTH, health)

    return {
        "status": "PASS",
        "rows": len(scored),
        "score_approved": approved,
        "matrix_path": str(OUT_MATRIX),
        "health_path": str(OUT_HEALTH),
    }


def main() -> None:
    print(json.dumps(export(), indent=2))


if __name__ == "__main__":
    main()
