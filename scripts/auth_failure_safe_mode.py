from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS_DIR = Path("docs/data/prediction_engine")
STATE_DIR = Path("state/prediction_engine")

DIAGNOSTIC_HEALTH = DOCS_DIR / "alpaca_source_diagnostic_health.json"
DIAGNOSTIC_FULL = DOCS_DIR / "alpaca_source_diagnostic.json"
SCANNER_STABLE = DOCS_DIR / "signal_dashboard_stable.json"
DATA_GUARD = DOCS_DIR / "signal_dashboard_data_guard_enriched.json"
RVOL_DASH = DOCS_DIR / "signal_dashboard_rvol_enriched.json"

OUT_DASHBOARD = DOCS_DIR / "signal_dashboard_safe_mode.json"
OUT_HEALTH = DOCS_DIR / "auth_failure_safe_mode_health.json"
OUT_STATE = STATE_DIR / "auth_failure_safe_mode.json"


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
        for key in ("rows", "signals", "candidates", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def choose_source_rows() -> tuple[str, list[dict[str, Any]]]:
    for path in [SCANNER_STABLE, DATA_GUARD, RVOL_DASH]:
        payload = read_json(path, {})
        rows = rows_from(payload)
        if rows:
            return str(path), rows
    return "none", []


def auth_failed(health: dict[str, Any]) -> bool:
    blockers = health.get("blockers", []) if isinstance(health, dict) else []
    warnings = health.get("warnings", []) if isinstance(health, dict) else []

    joined = " ".join(map(str, blockers + warnings)).lower()

    return (
        "alpaca_trading_auth_failed_401" in blockers
        or "alpaca_auth_failed_401" in warnings
        or "401" in joined
        or health.get("trading_auth_ok") is False
        and health.get("iex_data_ok") is False
        and health.get("sip_data_ok") is False
    )


def safe_mode_row(row: dict[str, Any], reason: str) -> dict[str, Any]:
    new = dict(row)

    new["auth_safe_mode"] = True
    new["auth_safe_mode_reason"] = reason
    new["score_status_original"] = new.get("score_status")
    new["score_status"] = "ALPACA_AUTH_FAIL"
    new["trade_gate"] = "Blocked"
    new["trade_gate_reasons"] = list(dict.fromkeys(
        list(new.get("trade_gate_reasons") or []) + [reason]
    ))

    new["alert_eligible"] = False
    new["buy_setup_alert_blocked"] = True
    new["paper_order_allowed"] = False
    new["live_order_allowed"] = False

    return new


def export() -> dict[str, Any]:
    generated_at = now()

    diagnostic_health = read_json(DIAGNOSTIC_HEALTH, {})
    diagnostic_full = read_json(DIAGNOSTIC_FULL, {})

    source_path, rows = choose_source_rows()

    is_auth_failed = auth_failed(diagnostic_health)

    reason = "alpaca_auth_failed_401" if is_auth_failed else "alpaca_auth_ok_or_unknown"

    safe_rows = []
    for row in rows:
        if is_auth_failed:
            safe_rows.append(safe_mode_row(row, reason))
        elif row.get("auth_safe_mode") is True:
            # Preserve existing safe mode state if already set, preventing bypass
            safe_rows.append(dict(row))
        else:
            new = dict(row)
            new["auth_safe_mode"] = False
            new["auth_safe_mode_reason"] = reason
            safe_rows.append(new)

    blockers: list[str] = []
    warnings: list[str] = []

    if is_auth_failed:
        blockers.append("alpaca_auth_failure_safe_mode_active")

    if not rows:
        warnings.append("no_signal_rows_available_for_safe_mode")

    status = "FAIL" if blockers else "PASS"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "auth_failure_safe_mode_health_v1",
        "generated_at": generated_at,
        "status": status,
        "safe_mode_active": is_auth_failed,
        "blockers": blockers,
        "warnings": warnings,
        "source_path": source_path,
        "rows": len(rows),
        "safe_rows": len(safe_rows),
        "diagnostic_status": diagnostic_health.get("status") if isinstance(diagnostic_health, dict) else "UNKNOWN",
        "trading_auth_ok": diagnostic_health.get("trading_auth_ok") if isinstance(diagnostic_health, dict) else None,
        "iex_data_ok": diagnostic_health.get("iex_data_ok") if isinstance(diagnostic_health, dict) else None,
        "sip_data_ok": diagnostic_health.get("sip_data_ok") if isinstance(diagnostic_health, dict) else None,
        "order_submission": False,
        "live_trading": False,
        "message": (
            "Auth safe mode blocks buy alerts and order eligibility when Alpaca auth/data "
            "diagnostic reports 401 or all data feeds fail."
        ),
    }

    dashboard = {
        "schema_version": "signal_dashboard_safe_mode_v1",
        "generated_at": generated_at,
        "status": status,
        "safe_mode_active": is_auth_failed,
        "reason": reason,
        "rows": safe_rows,
        "health": health,
        "diagnostic": {
            "health": diagnostic_health,
            "summary_available": bool(diagnostic_full),
        },
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "purpose": "Auth-failure safe dashboard. Does not submit orders.",
        },
    }

    write_json(OUT_DASHBOARD, dashboard)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, dashboard)

    return {
        "status": status,
        "safe_mode_active": is_auth_failed,
        "rows": len(rows),
        "safe_rows": len(safe_rows),
        "blockers": blockers,
        "warnings": warnings,
        "dashboard_path": str(OUT_DASHBOARD),
        "health_path": str(OUT_HEALTH),
    }


def main() -> None:
    print(json.dumps(export(), indent=2))


if __name__ == "__main__":
    main()
