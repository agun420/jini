from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prediction_engine.execution.asymmetric_slip import AsymmetricSlippageEngine


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

BUY_ALERT_MODE = DOCS / "buy_order_alert_mode.json"

OUT_DOCS = DOCS / "slippage_quality.json"
OUT_HEALTH = DOCS / "slippage_quality_health.json"
OUT_STATE = STATE / "slippage_quality.json"


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
        return float(value)
    except Exception:
        return default


def ticker(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def price(row: dict[str, Any]) -> float:
    for key in ("price", "last_price", "close", "last", "mark"):
        x = f(row.get(key), 0.0)
        if x > 0:
            return x
    return 0.0


def main() -> None:
    generated_at = now()
    engine = AsymmetricSlippageEngine()

    source = read_json(BUY_ALERT_MODE, {})
    rows = rows_from(source)
    eligible = [r for r in rows if r.get("buy_order_alert_eligible") is True]

    blockers = []
    warnings = []

    if not rows:
        blockers.append("buy_order_alert_rows_missing")

    audits = []

    for row in eligible:
        sym = ticker(row)
        p = price(row)

        # Conservative defaults until real spread/volume fields are consistently available.
        spread_pct = f(row.get("spread_pct"), 0.008)
        bar_vol = f(row.get("volume") or row.get("bar_volume"), 100000)
        avg_vol = f(row.get("avg_volume") or row.get("average_volume"), 100000)
        atr = f(row.get("atr") or row.get("atr_14"), max(p * 0.01, 0.05))

        entry = engine.generate_fill_profile(
            order_type="ENTRY_MARKET",
            raw_price=p,
            spread_pct=spread_pct,
            bar_vol=bar_vol,
            avg_vol=avg_vol,
            atr=atr,
        )

        profit_exit_price = p * (1 + f(row.get("validated_target_pct"), 0.6) / 100)
        stop_exit_price = p * (1 - f(row.get("validated_stop_pct"), 0.8) / 100)

        profit = engine.generate_fill_profile(
            order_type="LIMIT_PROFIT",
            raw_price=profit_exit_price,
            spread_pct=spread_pct,
            bar_vol=bar_vol,
            avg_vol=avg_vol,
            atr=atr,
        )

        stop = engine.generate_fill_profile(
            order_type="STOP_PANIC",
            raw_price=stop_exit_price,
            spread_pct=spread_pct,
            bar_vol=bar_vol,
            avg_vol=avg_vol,
            atr=atr,
        )

        execution_quality_pass = (
            entry.get("execution_quality_pass") is True
            and profit.get("execution_quality_pass") is True
            and stop.get("data_quality_flag") == "OK"
        )

        block_reasons = []
        for label, profile in [
            ("entry", entry),
            ("profit", profit),
            ("stop", stop),
        ]:
            if profile.get("block_reason"):
                block_reasons.append(f"{label}_{profile.get('block_reason')}")

        audits.append({
            "ticker": sym,
            "price": p,
            "buy_order_alert_status": row.get("buy_order_alert_status"),
            "score_v2": f(row.get("score_v2")),
            "execution_quality_pass": execution_quality_pass,
            "block_reasons": block_reasons,
            "entry_profile": entry,
            "profit_profile": profit,
            "stop_profile": stop,
            "order_submission": False,
            "live_trading": False,
        })

    passed = [a for a in audits if a.get("execution_quality_pass") is True]
    failed = [a for a in audits if a.get("execution_quality_pass") is False]

    if failed:
        warnings.append("some_alert_rows_failed_slippage_quality")

    avg_entry_slip = (
        sum(float(a["entry_profile"].get("slippage_pct") or 0) for a in audits) / len(audits)
        if audits else 0
    )

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "slippage_quality_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "eligible_rows_audited": len(audits),
        "execution_quality_pass": len(passed),
        "execution_quality_fail": len(failed),
        "avg_entry_slippage_pct": round(avg_entry_slip, 5),
        "slippage_model_ready": True,
        "paper_auto_trade_ready": False,
        "auto_trade_ready": False,
        "live_trade_ready": False,
        "order_submission": False,
        "live_trading": False,
    }

    payload = {
        "schema_version": "slippage_quality_v1",
        "generated_at": generated_at,
        "health": health,
        "audits": audits,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
            "purpose": "Research-only slippage quality audit.",
        },
    }

    write_json(OUT_DOCS, payload)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, payload)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
