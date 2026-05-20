from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

BUY_ALERT_MODE = DOCS / "buy_order_alert_mode.json"
BUY_ALERT_HEALTH = DOCS / "buy_order_alert_mode_health.json"

OUT_DOCS = DOCS / "buy_order_alert_outcome_journal.json"
OUT_HEALTH = DOCS / "buy_order_alert_outcome_journal_health.json"
OUT_STATE = STATE / "buy_order_alert_outcome_journal.json"


def now_dt() -> datetime:
    return datetime.now(timezone.utc)


def now() -> str:
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


def ticker(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def price(row: dict[str, Any]) -> float:
    for key in ("price", "last_price", "close", "last", "mark"):
        x = f(row.get(key), 0.0)
        if x > 0:
            return x
    return 0.0


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        s = str(value).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        return None


def make_alert_id(sym: str, setup: str, alert_ts: datetime) -> str:
    # One alert bucket per ticker/setup per 30-minute block.
    bucket_minute = (alert_ts.minute // 30) * 30
    bucket = alert_ts.replace(minute=bucket_minute, second=0, microsecond=0)
    return f"{sym}_{setup}_{bucket.strftime('%Y%m%dT%H%MZ')}"


def fetch_symbol_bars(symbol: str, start: datetime, end: datetime) -> list[Any]:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from alpaca.data.enums import DataFeed

    key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
    secret = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")

    if not key or not secret:
        raise RuntimeError("missing_alpaca_key_or_secret")

    feed_name = str(os.getenv("ALPACA_DATA_FEED") or "iex").upper()
    feed = DataFeed.SIP if feed_name == "SIP" else DataFeed.IEX

    client = StockHistoricalDataClient(key, secret)

    bars = client.get_stock_bars(
        StockBarsRequest(
            symbol_or_symbols=[symbol],
            timeframe=TimeFrame.Minute,
            start=start,
            end=end,
            feed=feed,
        )
    )

    return list(bars.data.get(symbol, []))


def bar_close_at_or_after(bars: list[Any], target_time: datetime) -> float | None:
    for bar in bars:
        ts = getattr(bar, "timestamp", None)
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        ts = ts.astimezone(timezone.utc)
        if ts >= target_time:
            return float(bar.close)
    return None


def update_alert(alert: dict[str, Any]) -> dict[str, Any]:
    if alert.get("status") in {"TARGET_HIT", "STOP_HIT", "TIME_EXIT", "ERROR"}:
        return alert

    sym = str(alert.get("ticker") or "").upper()
    alert_time = parse_dt(alert.get("alert_ts"))
    deadline = parse_dt(alert.get("deadline_ts"))

    if not sym or not alert_time or not deadline:
        alert["status"] = "ERROR"
        alert["error"] = "missing_symbol_or_timestamps"
        return alert

    current_time = now_dt()

    # Alpaca free/standard historical queries can need a delay buffer.
    end = min(current_time - timedelta(minutes=20), deadline + timedelta(minutes=2))

    if end <= alert_time:
        alert["status"] = "OPEN"
        return alert

    try:
        bars = fetch_symbol_bars(sym, alert_time, end)
    except Exception as exc:
        alert["status"] = "OPEN"
        alert["last_update_error"] = str(exc)[:300]
        return alert

    if not bars:
        alert["status"] = "OPEN"
        alert["last_update_error"] = "no_bars_returned_yet"
        return alert

    entry = f(alert.get("alert_price"))
    target = f(alert.get("target_price"))
    stop = f(alert.get("stop_price"))

    max_high = max(float(b.high) for b in bars)
    min_low = min(float(b.low) for b in bars)
    latest_close = float(bars[-1].close)

    alert["latest_close"] = round(latest_close, 4)
    alert["max_favorable_move_pct"] = round(((max_high - entry) / entry) * 100, 4) if entry else 0
    alert["max_adverse_move_pct"] = round(((min_low - entry) / entry) * 100, 4) if entry else 0

    for minutes in [5, 10, 15, 30]:
        t = alert_time + timedelta(minutes=minutes)
        c = bar_close_at_or_after(bars, t)
        if c is not None:
            alert[f"price_after_{minutes}m"] = round(c, 4)
            alert[f"return_after_{minutes}m_pct"] = round(((c - entry) / entry) * 100, 4) if entry else 0

    # Conservative ordering: if target and stop hit on same minute, count stop first.
    for b in bars:
        ts = getattr(b, "timestamp", None)
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        ts = ts.astimezone(timezone.utc)

        hi = float(b.high)
        lo = float(b.low)

        if lo <= stop:
            alert["status"] = "STOP_HIT"
            alert["resolved_ts"] = ts.isoformat()
            alert["result_return_pct"] = round(((stop - entry) / entry) * 100, 4) if entry else 0
            return alert

        if hi >= target:
            alert["status"] = "TARGET_HIT"
            alert["resolved_ts"] = ts.isoformat()
            alert["result_return_pct"] = round(((target - entry) / entry) * 100, 4) if entry else 0
            return alert

    if current_time >= deadline + timedelta(minutes=20):
        alert["status"] = "TIME_EXIT"
        alert["resolved_ts"] = deadline.isoformat()
        exit_price = alert.get("price_after_30m") or latest_close
        alert["result_return_pct"] = round(((float(exit_price) - entry) / entry) * 100, 4) if entry else 0
    else:
        alert["status"] = "OPEN"

    return alert


def main() -> None:
    generated_at = now()
    current_time = now_dt()

    buy_mode = read_json(BUY_ALERT_MODE, {})
    buy_health = read_json(BUY_ALERT_HEALTH, {})
    existing_payload = read_json(OUT_STATE, {})
    existing_alerts = existing_payload.get("alerts", []) if isinstance(existing_payload, dict) else []

    blockers: list[str] = []
    warnings: list[str] = []

    if buy_health.get("status") != "PASS":
        blockers.append("buy_order_alert_mode_not_pass")

    if buy_health.get("order_submission") is not False:
        blockers.append("buy_order_alert_mode_order_submission_not_false")

    if buy_health.get("live_trading") is not False:
        blockers.append("buy_order_alert_mode_live_trading_not_false")

    rows = rows_from(buy_mode)
    eligible_rows = [r for r in rows if r.get("buy_order_alert_eligible") is True]

    if not rows:
        blockers.append("buy_order_alert_rows_missing")

    alerts_by_id = {
        str(a.get("alert_id")): dict(a)
        for a in existing_alerts
        if isinstance(a, dict) and a.get("alert_id")
    }

    created_count = 0

    if not blockers:
        for row in eligible_rows:
            sym = ticker(row)
            p = price(row)
            setup = str(row.get("validated_setup") or "price_10_to_75_reclaim_5bar_high_light")
            target_pct = f(row.get("validated_target_pct"), 0.6)
            stop_pct = f(row.get("validated_stop_pct"), 0.8)
            horizon = int(f(row.get("validated_horizon_minutes"), 30))

            if not sym or p <= 0:
                continue

            alert_id = make_alert_id(sym, setup, current_time)

            # Duplicate lock: do not create same symbol/setup alert in same 30-min bucket.
            if alert_id in alerts_by_id:
                continue

            target_price = p * (1 + target_pct / 100)
            stop_price = p * (1 - stop_pct / 100)

            alerts_by_id[alert_id] = {
                "alert_id": alert_id,
                "schema_version": "buy_order_alert_outcome_v1",
                "created_at": generated_at,
                "alert_ts": current_time.isoformat(),
                "deadline_ts": (current_time + timedelta(minutes=horizon)).isoformat(),
                "ticker": sym,
                "alert_price": round(p, 4),
                "target_price": round(target_price, 4),
                "stop_price": round(stop_price, 4),
                "target_pct": target_pct,
                "stop_pct": stop_pct,
                "horizon_minutes": horizon,
                "score_v2": f(row.get("score_v2")),
                "setup": setup,
                "validated_profit_factor": f(row.get("validated_profit_factor")),
                "validated_avg_return_pct": f(row.get("validated_avg_return_pct")),
                "validated_total_tests": int(f(row.get("validated_total_tests"))),
                "status": "OPEN",
                "order_submission": False,
                "live_trading": False,
                "paper_order_allowed": False,
                "live_order_allowed": False,
            }
            created_count += 1

    updated_alerts = []
    for alert in alerts_by_id.values():
        updated_alerts.append(update_alert(dict(alert)))

    updated_alerts.sort(key=lambda a: str(a.get("alert_ts") or ""), reverse=True)

    total_alerts = len(updated_alerts)
    open_alerts = sum(1 for a in updated_alerts if a.get("status") == "OPEN")
    target_hits = sum(1 for a in updated_alerts if a.get("status") == "TARGET_HIT")
    stop_hits = sum(1 for a in updated_alerts if a.get("status") == "STOP_HIT")
    time_exits = sum(1 for a in updated_alerts if a.get("status") == "TIME_EXIT")
    errors = sum(1 for a in updated_alerts if a.get("status") == "ERROR")

    closed = [a for a in updated_alerts if a.get("status") in {"TARGET_HIT", "STOP_HIT", "TIME_EXIT"}]
    avg_result = (
        sum(f(a.get("result_return_pct")) for a in closed) / len(closed)
        if closed else 0
    )

    if total_alerts < 100:
        warnings.append("live_alert_outcome_sample_below_100")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "buy_order_alert_outcome_journal_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "eligible_rows_seen": len(eligible_rows),
        "alerts_created_this_run": created_count,
        "total_alerts": total_alerts,
        "open_alerts": open_alerts,
        "closed_alerts": len(closed),
        "target_hits": target_hits,
        "stop_hits": stop_hits,
        "time_exits": time_exits,
        "errors": errors,
        "target_hit_rate_closed_pct": round((target_hits / len(closed)) * 100, 2) if closed else 0,
        "stop_hit_rate_closed_pct": round((stop_hits / len(closed)) * 100, 2) if closed else 0,
        "avg_result_return_pct": round(avg_result, 4),
        "paper_auto_trade_ready": False,
        "auto_trade_ready": False,
        "live_trade_ready": False,
        "order_submission": False,
        "live_trading": False,
    }

    payload = {
        "schema_version": "buy_order_alert_outcome_journal_v1",
        "generated_at": generated_at,
        "health": health,
        "alerts": updated_alerts,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
            "purpose": "Tracks buy order alert outcomes only. Does not submit orders.",
        },
    }

    write_json(OUT_DOCS, payload)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, payload)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
