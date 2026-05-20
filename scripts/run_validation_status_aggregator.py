from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

VALIDATION_CORE_MANIFEST = DOCS / "validation_core_manifest_health.json"
TRADE_JOURNAL_HEALTH = DOCS / "trade_journal_health.json"
BLOCKED_JOURNAL_HEALTH = DOCS / "blocked_journal_health.json"
SLIPPAGE_HEALTH = DOCS / "slippage_quality_health.json"
FORWARD_VALIDATION_HEALTH = DOCS / "forward_validation_health.json"
AUTO_TRADE_READINESS = DOCS / "auto_trade_readiness_health.json"
BUY_ALERT_OUTCOME = DOCS / "buy_order_alert_outcome_journal_health.json"
FEED_STATUS = DOCS / "feed_status_health.json"

OUT_DOCS = DOCS / "validation_status.json"
OUT_HEALTH = DOCS / "validation_status_health.json"
OUT_STATE = STATE / "validation_status.json"


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


def status_of(payload: dict[str, Any]) -> str:
    return str(payload.get("status") or "MISSING").upper()


def main() -> None:
    generated_at = now()

    manifest = read_json(VALIDATION_CORE_MANIFEST, {})
    trade = read_json(TRADE_JOURNAL_HEALTH, {})
    blocked = read_json(BLOCKED_JOURNAL_HEALTH, {})
    slippage = read_json(SLIPPAGE_HEALTH, {})
    forward = read_json(FORWARD_VALIDATION_HEALTH, {})
    auto = read_json(AUTO_TRADE_READINESS, {})
    outcome = read_json(BUY_ALERT_OUTCOME, {})
    feed = read_json(FEED_STATUS, {})

    blockers: list[str] = []
    warnings: list[str] = []

    required_files = {
        "validation_core_manifest": manifest,
        "trade_journal": trade,
        "blocked_journal": blocked,
        "slippage_quality": slippage,
        "forward_validation": forward,
        "auto_trade_readiness": auto,
        "buy_order_alert_outcome_journal": outcome,
        "feed_status": feed,
    }

    for name, payload in required_files.items():
        if not payload:
            blockers.append(f"{name}_missing")
        elif payload.get("_read_error"):
            blockers.append(f"{name}_read_error")

    for name, payload in required_files.items():
        if payload and status_of(payload) == "FAIL":
            blockers.append(f"{name}_failed")
        elif payload and status_of(payload) == "WARN":
            warnings.append(f"{name}_warn")

    validation_core_ready = not blockers

    closed_trades = int(trade.get("closed_trades") or 0)
    blocked_records = int(blocked.get("total_records") or 0)
    total_alerts = int(outcome.get("total_alerts") or 0)
    closed_alerts = int(outcome.get("closed_alerts") or 0)
    forward_ready = bool(forward.get("forward_validation_ready"))
    slippage_ready = bool(slippage.get("slippage_model_ready"))
    feed_data_ready = bool(feed.get("can_allow_buy_alerts_from_data"))

    # Promotion logic. This is intentionally strict.
    buy_order_alert_ready = bool(auto.get("buy_order_alert_ready"))
    paper_auto_trade_ready = False
    auto_trade_ready = False
    live_trade_ready = False

    paper_auto_trade_blockers = []

    if not buy_order_alert_ready:
        paper_auto_trade_blockers.append("buy_order_alert_not_ready")

    if total_alerts < 100:
        paper_auto_trade_blockers.append("live_alert_outcome_sample_below_100")

    if closed_alerts < 50:
        paper_auto_trade_blockers.append("closed_alert_sample_below_50")

    if closed_trades < 30:
        paper_auto_trade_blockers.append("closed_trade_sample_below_30")

    if not slippage_ready:
        paper_auto_trade_blockers.append("slippage_model_not_ready")

    if feed.get("status") == "FAIL":
        paper_auto_trade_blockers.append("feed_status_failed")

    if feed.get("can_allow_buy_alerts_from_data") is not True:
        paper_auto_trade_blockers.append("feed_data_not_allowed")

    if not forward_ready:
        paper_auto_trade_blockers.append("forward_validation_not_ready")

    if auto.get("order_submission") is not False:
        paper_auto_trade_blockers.append("auto_trade_readiness_order_submission_not_false")

    if auto.get("live_trading") is not False:
        paper_auto_trade_blockers.append("auto_trade_readiness_live_trading_not_false")

    if paper_auto_trade_blockers:
        warnings.append("paper_auto_trade_still_blocked")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "validation_status_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "validation_core_ready": validation_core_ready,
        "buy_order_alert_ready": buy_order_alert_ready,
        "paper_auto_trade_ready": paper_auto_trade_ready,
        "auto_trade_ready": auto_trade_ready,
        "live_trade_ready": live_trade_ready,
        "paper_auto_trade_blockers": paper_auto_trade_blockers,
        "closed_trades": closed_trades,
        "blocked_records": blocked_records,
        "total_alerts": total_alerts,
        "closed_alerts": closed_alerts,
        "slippage_model_ready": slippage_ready,
        "forward_validation_ready": forward_ready,
        "feed_data_ready": feed_data_ready,
        "feed_status": feed.get("status"),
        "feed_rows_usable_for_buy_alert": feed.get("rows_usable_for_buy_alert"),
        "feed_rows_blocked_by_data_quality": feed.get("rows_blocked_by_data_quality"),
        "order_submission": False,
        "live_trading": False,
    }

    payload = {
        "schema_version": "validation_status_v1",
        "generated_at": generated_at,
        "health": health,
        "modules": {
            "validation_core_manifest": manifest,
            "trade_journal": trade,
            "blocked_journal": blocked,
            "slippage_quality": slippage,
            "forward_validation": forward,
            "auto_trade_readiness": auto,
            "buy_order_alert_outcome_journal": outcome,
        "feed_status": feed,
        },
        "promotion_ladder": [
            {
                "level": 1,
                "name": "Buy order alert",
                "ready": buy_order_alert_ready,
            },
            {
                "level": 2,
                "name": "Evidence collection",
                "ready": total_alerts >= 100 and closed_alerts >= 50,
            },
            {
                "level": 3,
                "name": "Forward validation",
                "ready": forward_ready,
            },
            {
                "level": 4,
                "name": "Paper auto-trade review",
                "ready": paper_auto_trade_ready,
            },
            {
                "level": 5,
                "name": "Live-readiness review",
                "ready": live_trade_ready,
            },
        ],
        "safety": {
            "auto_config_overwrite": False,
            "order_submission": False,
            "live_trading": False,
            "purpose": "Aggregate validation status only. Does not trade.",
        },
    }

    write_json(OUT_DOCS, payload)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, payload)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
