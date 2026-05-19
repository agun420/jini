from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

OPERATOR_HEALTH = DOCS / "operator_health.json"
FINAL_AUDIT = DOCS / "final_repo_audit.json"

OUT_DOCS = DOCS / "operator_stability_health.json"
OUT_STATE = STATE / "operator_stability_health.json"


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


def main() -> None:
    generated_at = now()

    operator = read_json(OPERATOR_HEALTH, {})
    audit = read_json(FINAL_AUDIT, {})
    audit_score = audit.get("score", {}) if isinstance(audit, dict) else {}

    blockers: list[str] = []
    warnings: list[str] = []

    operator_status = operator.get("status")
    audit_status = audit.get("status")
    audit_grade = audit_score.get("grade")
    audit_points = audit_score.get("score")

    if operator_status not in {"PASS", "WARN"}:
        blockers.append("operator_health_not_pass_or_warn")

    if audit_status != "PASS":
        blockers.append("final_audit_not_pass")

    if audit_grade != "PASS":
        blockers.append("final_audit_grade_not_pass")

    if audit_points != 100:
        blockers.append("final_audit_not_100")

    if operator.get("safe_mode_active") is True:
        blockers.append("safe_mode_active")

    if operator.get("trading_auth_ok") is not True:
        blockers.append("alpaca_trading_auth_not_ok")

    if not (operator.get("iex_data_ok") is True or operator.get("sip_data_ok") is True):
        blockers.append("alpaca_data_feed_not_ok")

    if int(operator.get("rows_with_price") or 0) <= 0:
        blockers.append("no_priced_rows")

    if int(operator.get("rows_with_score") or 0) <= 0:
        blockers.append("no_scored_rows")

    if int(operator.get("zero_price_rows") or 0) > 0:
        blockers.append("zero_price_rows_detected")

    if operator.get("order_submission") is not False:
        blockers.append("order_submission_not_false")

    if operator.get("live_trading") is not False:
        blockers.append("live_trading_not_false")

    if int(operator.get("trade_eligible") or 0) == 0:
        warnings.append("no_trade_eligible_rows_currently")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    payload = {
        "schema_version": "operator_stability_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "operator_status": operator_status,
        "final_audit_status": audit_status,
        "final_audit_grade": audit_grade,
        "final_audit_score": audit_points,
        "safe_mode_active": operator.get("safe_mode_active"),
        "trading_auth_ok": operator.get("trading_auth_ok"),
        "iex_data_ok": operator.get("iex_data_ok"),
        "sip_data_ok": operator.get("sip_data_ok"),
        "rows": operator.get("rows"),
        "rows_with_price": operator.get("rows_with_price"),
        "rows_with_score": operator.get("rows_with_score"),
        "zero_price_rows": operator.get("zero_price_rows"),
        "trade_eligible": operator.get("trade_eligible"),
        "watch_only": operator.get("watch_only"),
        "order_submission": operator.get("order_submission"),
        "live_trading": operator.get("live_trading"),
        "message": "Stability check for consolidated Jini operator pipeline.",
    }

    write_json(OUT_DOCS, payload)
    write_json(OUT_STATE, payload)

    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
