from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS_DIR = Path("docs/data/prediction_engine")
STATE_DIR = Path("state/prediction_engine")

INPUTS = {
    "production_monitor": DOCS_DIR / "production_monitor_health.json",
    "meta_predictions": DOCS_DIR / "meta_labeling_predictions.json",
    "signal_dashboard": DOCS_DIR / "signal_dashboard_rvol_enriched.json",
    "final_audit": DOCS_DIR / "final_repo_audit.json",
}

STATE_ALERT_HISTORY = STATE_DIR / "alert_history.json"

OUT_ALERTS = DOCS_DIR / "alert_delivery.json"
OUT_HEALTH = DOCS_DIR / "alert_delivery_health.json"
OUT_STATE = STATE_DIR / "alert_delivery.json"

DASHBOARD_URL = os.getenv("JINI_DASHBOARD_URL", "https://agun420.github.io/jini/")


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
        for key in ("rows", "signals", "candidates", "items", "data", "predictions"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]

    return []


def load_alert_history() -> dict[str, Any]:
    payload = read_json(STATE_ALERT_HISTORY, {})
    if not isinstance(payload, dict):
        return {"sent": {}}
    payload.setdefault("sent", {})
    return payload


def save_alert_history(history: dict[str, Any]) -> None:
    write_json(STATE_ALERT_HISTORY, history)


def alert_id(kind: str, key: str, bucket: str) -> str:
    raw = f"{kind}|{key}|{bucket}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def time_bucket() -> str:
    current = datetime.now(timezone.utc)
    return current.strftime("%Y-%m-%dT%H:%M")


def f(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def telegram_configured() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))


def send_telegram(text: str) -> dict[str, Any]:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        return {
            "sent": False,
            "reason": "telegram_not_configured",
        }

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=15) as response:
            body = response.read().decode("utf-8", errors="ignore")
            return {
                "sent": True,
                "status_code": response.status,
                "response": body[:500],
            }
    except Exception as exc:
        return {
            "sent": False,
            "reason": "telegram_send_failed",
            "error": str(exc),
        }


def build_system_alerts() -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []

    monitor = read_json(INPUTS["production_monitor"], {})
    audit = read_json(INPUTS["final_audit"], {})

    monitor_status = monitor.get("status") if isinstance(monitor, dict) else None
    audit_status = audit.get("status") if isinstance(audit, dict) else None

    blockers = monitor.get("blockers", []) if isinstance(monitor, dict) else []
    warnings = monitor.get("warnings", []) if isinstance(monitor, dict) else []

    if monitor_status == "FAIL":
        alerts.append({
            "kind": "SYSTEM_HEALTH_ALERT",
            "severity": "HIGH",
            "key": "production_monitor_fail",
            "title": "SYSTEM HEALTH ALERT: Production monitor failed",
            "message": (
                "SYSTEM HEALTH ALERT\n"
                "Production monitor status: FAIL\n"
                f"Blockers: {', '.join(blockers) if blockers else 'None listed'}\n"
                f"Warnings: {', '.join(warnings) if warnings else 'None listed'}\n"
                f"Dashboard: {DASHBOARD_URL}\n"
                "Paper/research only. No live order submitted."
            ),
        })

    if monitor_status == "WARN":
        alerts.append({
            "kind": "SYSTEM_HEALTH_ALERT",
            "severity": "MEDIUM",
            "key": "production_monitor_warn",
            "title": "SYSTEM HEALTH ALERT: Production monitor warning",
            "message": (
                "SYSTEM HEALTH ALERT\n"
                "Production monitor status: WARN\n"
                f"Warnings: {', '.join(warnings) if warnings else 'None listed'}\n"
                f"Dashboard: {DASHBOARD_URL}\n"
                "Paper/research only. No live order submitted."
            ),
        })

    if audit_status != "PASS":
        alerts.append({
            "kind": "SYSTEM_HEALTH_ALERT",
            "severity": "HIGH",
            "key": "final_audit_not_pass",
            "title": "SYSTEM HEALTH ALERT: Final audit not PASS",
            "message": (
                "SYSTEM HEALTH ALERT\n"
                f"Final repo audit status: {audit_status or 'UNKNOWN'}\n"
                f"Dashboard: {DASHBOARD_URL}\n"
                "Paper/research only. No live order submitted."
            ),
        })

    return alerts


def get_signal_map() -> dict[str, dict[str, Any]]:
    payload = read_json(INPUTS["signal_dashboard"], {})
    rows = rows_from(payload)

    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        ticker = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
        if ticker:
            out[ticker] = row

    return out


def build_buy_setup_alerts() -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []

    meta_payload = read_json(INPUTS["meta_predictions"], {})
    predictions = rows_from(meta_payload)
    signal_map = get_signal_map()

    for item in predictions:
        ticker = str(item.get("ticker") or "").upper().strip()
        if not ticker:
            continue

        signal = signal_map.get(ticker, {})

        probability = f(item.get("probability_target_before_stop_pct"), 0.0) or 0.0
        decision = str(item.get("model_decision") or "")
        final_score = f(signal.get("final_trade_score"), 0.0) or 0.0
        runner = f(signal.get("runner_potential_score"), 0.0) or 0.0
        entry = f(signal.get("entry_quality_score"), 0.0) or 0.0
        danger = f(signal.get("danger_score"), 100.0) or 100.0
        rvol = f(signal.get("time_slot_rvol"), 0.0) or 0.0
        score_status = str(signal.get("score_status") or "")
        second_leg = str(signal.get("second_leg_state") or "N/A")
        price = signal.get("price") or signal.get("last_price") or signal.get("close") or "N/A"
        target = item.get("selected_target_pct", "N/A")
        stop = item.get("selected_stop_pct", "N/A")

        strict_score_gate = (
            final_score >= 82
            and runner >= 80
            and entry >= 78
            and danger <= 25
            and probability >= 65
            and score_status in {"TRADE_ELIGIBLE_SCORE_APPROVED", "WAIT_FOR_PULLBACK", "ALERT_ONLY"}
        )

        strong_gate = (
            strict_score_gate
            and probability >= 70
            and second_leg == "SECOND_LEG_CONFIRMED"
        )

        if strong_gate:
            kind = "STRONG_BUY_SETUP_ALERT"
            severity = "HIGH"
            label = "STRONG BUY SETUP ALERT"
        elif strict_score_gate:
            kind = "BUY_SETUP_WATCH"
            severity = "MEDIUM"
            label = "BUY SETUP WATCH"
        elif score_status == "WAIT_FOR_PULLBACK" and probability >= 60 and danger <= 35:
            kind = "WAIT_FOR_PULLBACK_ALERT"
            severity = "LOW"
            label = "WAIT FOR PULLBACK ALERT"
        else:
            continue

        reasons = item.get("model_reasons") or []
        blocks = signal.get("score_blocks") or signal.get("second_leg_blocks") or []

        alerts.append({
            "kind": kind,
            "severity": severity,
            "key": ticker,
            "title": f"{label}: {ticker}",
            "ticker": ticker,
            "message": (
                f"{label}: {ticker}\n"
                f"Price: {price}\n"
                f"ML probability: {probability:.2f}%\n"
                f"Final score: {final_score:.2f}\n"
                f"Runner: {runner:.2f} | Entry: {entry:.2f} | Danger: {danger:.2f}\n"
                f"Time-slot RVOL: {rvol:.2f}\n"
                f"Second-leg state: {second_leg}\n"
                f"Score status: {score_status or 'N/A'}\n"
                f"Target/stop profile: +{target}% / -{stop}%\n"
                f"Reasons: {', '.join(map(str, reasons)) if reasons else 'None listed'}\n"
                f"Blocks: {', '.join(map(str, blocks)) if blocks else 'None listed'}\n"
                f"Dashboard: {DASHBOARD_URL}\n"
                "Paper/research only. Not financial advice. No live order submitted."
            ),
        })

    return alerts


def should_send(alert: dict[str, Any], history: dict[str, Any]) -> tuple[bool, str]:
    bucket = time_bucket()
    if alert["kind"] in {"SYSTEM_HEALTH_ALERT"}:
        bucket = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")

    aid = alert_id(alert["kind"], alert["key"], bucket)
    sent = history.get("sent", {})

    if aid in sent:
        return False, aid

    return True, aid


def export(send_enabled: bool = True) -> dict[str, Any]:
    generated_at = now()
    history = load_alert_history()

    candidate_alerts = build_system_alerts() + build_buy_setup_alerts()

    delivered = []
    skipped = []

    for alert in candidate_alerts:
        allowed, aid = should_send(alert, history)
        alert["alert_id"] = aid

        if not allowed:
            alert["delivery_status"] = "duplicate_suppressed"
            skipped.append(alert)
            continue

        if send_enabled:
            result = send_telegram(alert["message"])
        else:
            result = {"sent": False, "reason": "send_disabled"}

        alert["delivery_result"] = result
        alert["delivery_status"] = "sent" if result.get("sent") else "not_sent"

        history.setdefault("sent", {})[aid] = {
            "generated_at": generated_at,
            "kind": alert["kind"],
            "key": alert["key"],
            "title": alert["title"],
            "delivery_status": alert["delivery_status"],
        }

        delivered.append(alert)

    save_alert_history(history)

    payload = {
        "schema_version": "alert_delivery_v1",
        "generated_at": generated_at,
        "status": "PASS",
        "telegram_configured": telegram_configured(),
        "send_enabled": send_enabled,
        "candidate_alert_count": len(candidate_alerts),
        "delivered_count": len(delivered),
        "skipped_count": len(skipped),
        "alerts": candidate_alerts,
        "delivered": delivered,
        "skipped": skipped,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "purpose": "Alerting only. Does not submit orders.",
        },
    }

    health = {
        "schema_version": "alert_delivery_health_v1",
        "generated_at": generated_at,
        "status": "PASS",
        "telegram_configured": telegram_configured(),
        "candidate_alert_count": len(candidate_alerts),
        "delivered_count": len(delivered),
        "skipped_count": len(skipped),
        "order_submission": False,
        "live_trading": False,
    }

    write_json(OUT_ALERTS, payload)
    write_json(OUT_STATE, payload)
    write_json(OUT_HEALTH, health)

    return {
        "status": "PASS",
        "telegram_configured": telegram_configured(),
        "candidate_alert_count": len(candidate_alerts),
        "delivered_count": len(delivered),
        "skipped_count": len(skipped),
        "alerts_path": str(OUT_ALERTS),
        "health_path": str(OUT_HEALTH),
    }


def main() -> None:
    send_enabled = os.getenv("ALERT_SEND_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    print(json.dumps(export(send_enabled=send_enabled), indent=2))


if __name__ == "__main__":
    main()
