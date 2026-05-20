from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

RESEARCH_ALERTS = DOCS / "v3_research_alert_score.json"
ENRICHED_ROWS = DOCS / "v3_enriched_rows.json"

OUT_DOCS = DOCS / "v3_research_alert_outcome_journal.json"
OUT_HEALTH = DOCS / "v3_research_alert_outcome_journal_health.json"
OUT_STATE = STATE / "v3_research_alert_outcome_journal.json"


TARGET_PCT = 0.60
STOP_PCT = 0.80
TIME_EXIT_MINUTES = 30


def now_dt() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_dt().isoformat()


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


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def ticker(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def rows_from(payload: Any, key: str = "rows") -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


def current_price_map() -> dict[str, float]:
    payload = read_json(ENRICHED_ROWS, {})
    rows = rows_from(payload, "rows")
    out: dict[str, float] = {}

    for r in rows:
        sym = ticker(r)
        price = f(r.get("price"))
        if sym and price > 0:
            out[sym] = price

    return out


def make_alert_id(row: dict[str, Any], generated_at: str) -> str:
    sym = ticker(row)
    # one alert per ticker per generated minute to prevent duplicate spam
    bucket = generated_at[:16].replace(":", "").replace("-", "").replace("T", "_")
    return f"{sym}_{bucket}"


def main() -> None:
    generated_at = now_iso()
    current_time = now_dt()

    research_payload = read_json(RESEARCH_ALERTS, {})
    existing_payload = read_json(OUT_STATE, {"alerts": []})

    candidates = rows_from(research_payload, "candidates")
    all_rows = rows_from(research_payload, "rows")
    prices = current_price_map()

    existing_alerts = existing_payload.get("alerts", [])
    if not isinstance(existing_alerts, list):
        existing_alerts = []

    alerts_by_id = {
        str(a.get("alert_id")): a
        for a in existing_alerts
        if isinstance(a, dict) and a.get("alert_id")
    }

    blockers: list[str] = []
    warnings: list[str] = []

    if not all_rows:
        warnings.append("no_research_alert_rows_available")

    new_alerts = 0

    for row in candidates:
        sym = ticker(row)
        entry_price = f(row.get("price"))

        if not sym or entry_price <= 0:
            continue

        alert_id = make_alert_id(row, str(research_payload.get("generated_at") or generated_at))

        if alert_id in alerts_by_id:
            continue

        target_price = entry_price * (1 + TARGET_PCT / 100)
        stop_price = entry_price * (1 - STOP_PCT / 100)

        alert = {
            "alert_id": alert_id,
            "ticker": sym,
            "opened_at": generated_at,
            "status": "OPEN",
            "entry_price": round(entry_price, 4),
            "target_pct": TARGET_PCT,
            "stop_pct": STOP_PCT,
            "time_exit_minutes": TIME_EXIT_MINUTES,
            "target_price": round(target_price, 4),
            "stop_price": round(stop_price, 4),
            "last_price": round(prices.get(sym, entry_price), 4),
            "research_alert_score_v3": row.get("research_alert_score_v3"),
            "final_trade_score_v3": row.get("final_trade_score_v3"),
            "runner_potential_v3": row.get("runner_potential_v3"),
            "entry_quality_v3": row.get("entry_quality_v3"),
            "danger_score_v3": row.get("danger_score_v3"),
            "day_move_pct": row.get("day_move_pct"),
            "relative_volume": row.get("relative_volume"),
            "spread_pct": row.get("spread_pct"),
            "quote_age_sec": row.get("quote_age_sec"),
            "exit_price": None,
            "closed_at": None,
            "exit_reason": None,
            "return_pct": None,
            "order_submission": False,
            "live_trading": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
        }

        alerts_by_id[alert_id] = alert
        new_alerts += 1

    closed_now = 0

    for alert in alerts_by_id.values():
        if alert.get("status") != "OPEN":
            continue

        sym = str(alert.get("ticker") or "").upper()
        entry = f(alert.get("entry_price"))
        last = prices.get(sym, f(alert.get("last_price"), entry))

        if entry <= 0 or last <= 0:
            continue

        alert["last_price"] = round(last, 4)
        ret = ((last - entry) / entry) * 100
        alert["unrealized_return_pct"] = round(ret, 4)

        opened_at = parse_dt(alert.get("opened_at"))
        age_minutes = None
        if opened_at:
            age_minutes = (current_time - opened_at).total_seconds() / 60
            alert["age_minutes"] = round(age_minutes, 2)

        exit_reason = None

        if ret >= TARGET_PCT:
            exit_reason = "TARGET_HIT"
        elif ret <= -STOP_PCT:
            exit_reason = "STOP_HIT"
        elif age_minutes is not None and age_minutes >= TIME_EXIT_MINUTES:
            exit_reason = "TIME_EXIT"

        if exit_reason:
            alert["status"] = "CLOSED"
            alert["closed_at"] = generated_at
            alert["exit_price"] = round(last, 4)
            alert["exit_reason"] = exit_reason
            alert["return_pct"] = round(ret, 4)
            closed_now += 1

    alerts = list(alerts_by_id.values())
    alerts.sort(key=lambda a: str(a.get("opened_at") or ""), reverse=True)

    open_alerts = [a for a in alerts if a.get("status") == "OPEN"]
    closed_alerts = [a for a in alerts if a.get("status") == "CLOSED"]

    target_hits = [a for a in closed_alerts if a.get("exit_reason") == "TARGET_HIT"]
    stop_hits = [a for a in closed_alerts if a.get("exit_reason") == "STOP_HIT"]
    time_exits = [a for a in closed_alerts if a.get("exit_reason") == "TIME_EXIT"]

    realized_returns = [f(a.get("return_pct")) for a in closed_alerts if a.get("return_pct") is not None]
    avg_return = sum(realized_returns) / len(realized_returns) if realized_returns else 0.0

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "v3_research_alert_outcome_journal_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "new_alerts": new_alerts,
        "closed_now": closed_now,
        "total_alerts": len(alerts),
        "open_alerts": len(open_alerts),
        "closed_alerts": len(closed_alerts),
        "target_hits": len(target_hits),
        "stop_hits": len(stop_hits),
        "time_exits": len(time_exits),
        "avg_closed_return_pct": round(avg_return, 4),
        "target_pct": TARGET_PCT,
        "stop_pct": STOP_PCT,
        "time_exit_minutes": TIME_EXIT_MINUTES,
        "order_submission": False,
        "live_trading": False,
        "paper_order_allowed": False,
        "live_order_allowed": False,
    }

    out = {
        "schema_version": "v3_research_alert_outcome_journal_v1",
        "generated_at": generated_at,
        "health": health,
        "alerts": alerts,
        "open_alerts": open_alerts,
        "closed_alerts": closed_alerts,
        "safety": {
            "purpose": "Research alert outcome tracking only. Does not trade.",
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
