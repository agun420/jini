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
    bucket = generated_at[:16].replace(":", "").replace("-", "").replace("T", "_")
    return f"{sym}_{bucket}"


def opened_sort_key(alert: dict[str, Any]) -> str:
    return str(alert.get("opened_at") or "")


def dedupe_open_alerts(alerts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """
    Keep only one OPEN alert per ticker.
    Prefer newest opened_at. Mark older open duplicates as CLOSED/DUPLICATE_REPLACED.
    This prevents duplicate QBTS/WULF open rows from inflating live outcomes.
    """
    latest_open_by_ticker: dict[str, dict[str, Any]] = {}
    duplicate_count = 0

    for alert in alerts:
        if alert.get("status") != "OPEN":
            continue

        sym = str(alert.get("ticker") or "").upper()
        if not sym:
            continue

        existing = latest_open_by_ticker.get(sym)
        if existing is None:
            latest_open_by_ticker[sym] = alert
            continue

        current_time = opened_sort_key(alert)
        existing_time = opened_sort_key(existing)

        if current_time >= existing_time:
            existing["status"] = "CLOSED"
            existing["closed_at"] = now_iso()
            existing["exit_reason"] = "DUPLICATE_REPLACED"
            existing["return_pct"] = existing.get("unrealized_return_pct")
            latest_open_by_ticker[sym] = alert
        else:
            alert["status"] = "CLOSED"
            alert["closed_at"] = now_iso()
            alert["exit_reason"] = "DUPLICATE_REPLACED"
            alert["return_pct"] = alert.get("unrealized_return_pct")

        duplicate_count += 1

    return alerts, duplicate_count


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

    blockers: list[str] = []
    warnings: list[str] = []

    if not all_rows:
        warnings.append("no_research_alert_rows_available")

    # Normalize safety fields on existing alerts.
    alerts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for a in existing_alerts:
        if not isinstance(a, dict):
            continue
        alert_id = str(a.get("alert_id") or "")
        if not alert_id or alert_id in seen_ids:
            continue
        seen_ids.add(alert_id)

        a["order_submission"] = False
        a["live_trading"] = False
        a["paper_order_allowed"] = False
        a["live_order_allowed"] = False
        alerts.append(a)

    # First, de-dupe any current open duplicates before adding new alerts.
    alerts, duplicate_open_alerts_closed = dedupe_open_alerts(alerts)

    open_tickers = {
        str(a.get("ticker") or "").upper()
        for a in alerts
        if a.get("status") == "OPEN"
    }

    new_alerts = 0
    skipped_duplicate_open_ticker = 0

    for row in candidates:
        sym = ticker(row)
        entry_price = f(row.get("live_price") or row.get("price"))

        if not sym or entry_price <= 0:
            continue

        # Do not open another live research alert for same ticker.
        if sym in open_tickers:
            skipped_duplicate_open_ticker += 1
            continue

        alert_id = make_alert_id(row, str(research_payload.get("generated_at") or generated_at))
        if alert_id in seen_ids:
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
            "research_confidence": row.get("research_confidence"),
            "research_confidence_note": row.get("research_confidence_note"),
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

        alerts.append(alert)
        open_tickers.add(sym)
        seen_ids.add(alert_id)
        new_alerts += 1

    closed_now = 0

    for alert in alerts:
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

    # Final de-dupe pass after status updates.
    alerts, duplicate_closed_second_pass = dedupe_open_alerts(alerts)
    duplicate_open_alerts_closed += duplicate_closed_second_pass

    alerts.sort(key=lambda a: str(a.get("opened_at") or ""), reverse=True)

    open_alerts = [a for a in alerts if a.get("status") == "OPEN"]
    closed_alerts = [a for a in alerts if a.get("status") == "CLOSED"]

    target_hits = [a for a in closed_alerts if a.get("exit_reason") == "TARGET_HIT"]
    stop_hits = [a for a in closed_alerts if a.get("exit_reason") == "STOP_HIT"]
    time_exits = [a for a in closed_alerts if a.get("exit_reason") == "TIME_EXIT"]
    duplicate_replaced = [a for a in closed_alerts if a.get("exit_reason") == "DUPLICATE_REPLACED"]

    realized_returns = [
        f(a.get("return_pct"))
        for a in closed_alerts
        if a.get("return_pct") is not None
        and a.get("exit_reason") in {"TARGET_HIT", "STOP_HIT", "TIME_EXIT"}
    ]

    avg_return = sum(realized_returns) / len(realized_returns) if realized_returns else 0.0

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "v3_research_alert_outcome_journal_health_v2",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "new_alerts": new_alerts,
        "closed_now": closed_now,
        "duplicate_open_alerts_closed": duplicate_open_alerts_closed,
        "skipped_duplicate_open_ticker": skipped_duplicate_open_ticker,
        "total_alerts": len(alerts),
        "open_alerts": len(open_alerts),
        "closed_alerts": len(closed_alerts),
        "target_hits": len(target_hits),
        "stop_hits": len(stop_hits),
        "time_exits": len(time_exits),
        "duplicate_replaced": len(duplicate_replaced),
        "avg_closed_return_pct": round(avg_return, 4),
        "target_pct": TARGET_PCT,
        "stop_pct": STOP_PCT,
        "time_exit_minutes": TIME_EXIT_MINUTES,
        "one_open_alert_per_ticker": True,
        "order_submission": False,
        "live_trading": False,
        "paper_order_allowed": False,
        "live_order_allowed": False,
    }

    out = {
        "schema_version": "v3_research_alert_outcome_journal_v2",
        "generated_at": generated_at,
        "health": health,
        "alerts": alerts,
        "open_alerts": open_alerts,
        "closed_alerts": closed_alerts,
        "safety": {
            "purpose": "Research alert outcome tracking only. Does not trade.",
            "one_open_alert_per_ticker": True,
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
