from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

OUT_DASH = DOCS / "operator_dashboard.json"
OUT_HEALTH = DOCS / "operator_health.json"
OUT_STATE = STATE / "operator_dashboard.json"

INPUTS = {
    "runtime": DOCS / "runtime_heartbeat.json",
    "final_audit": DOCS / "final_repo_audit.json",
    "safe_mode": DOCS / "auth_failure_safe_mode_health.json",
    "alpaca_diag": DOCS / "alpaca_source_diagnostic_health.json",
    "scanner_source": DOCS / "scanner_data_source_health.json",
    "data_guard": DOCS / "data_feed_quality_health.json",
    "alerts": DOCS / "alert_delivery_health.json",
    "operator_resolver": DOCS / "operator_signal_resolver_health.json",
    "operator_signals": DOCS / "signal_dashboard_operator.json",
    "scored": DOCS / "signal_dashboard_scored.json",
    "stable": DOCS / "signal_dashboard_stable.json",
}


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


def n(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def ticker(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def price(row: dict[str, Any]) -> float | None:
    for key in ("price", "last_price", "close", "last", "mark"):
        v = n(row.get(key))
        if v is not None and v > 0:
            return v
    return None


def merge_rows() -> list[dict[str, Any]]:
    operator_payload = read_json(INPUTS["operator_signals"], {})
    scored_payload = read_json(INPUTS["scored"], {})
    stable_payload = read_json(INPUTS["stable"], {})

    merged: dict[str, dict[str, Any]] = {}

    # Scored rows first because they carry signal math.
    for source_name, payload in [
        ("scored", scored_payload),
        ("operator", operator_payload),
        ("stable", stable_payload),
    ]:
        for row in rows_from(payload):
            t = ticker(row)
            if not t:
                continue

            base = merged.get(t, {})
            new = dict(base)

            for key, value in row.items():
                # Never let blank / N/A overwrite useful values.
                if value in (None, "", "N/A"):
                    continue

                # Preserve score fields from scored/operator layers.
                if key in {
                    "final_trade_score",
                    "runner_potential_score",
                    "entry_quality_score",
                    "danger_score",
                    "score_status",
                    "second_leg_state",
                    "time_slot_rvol",
                    "probability_target_before_stop_pct",
                }:
                    if source_name in {"scored", "operator"} or key not in new:
                        new[key] = value
                    continue

                # Always accept real prices.
                if key in {"price", "last_price", "close", "last", "mark"}:
                    if n(value) is not None and float(value) > 0:
                        new["price"] = float(value)
                    continue

                # Keep useful data state.
                if key in {
                    "scanner_data_status",
                    "data_feed_guard_status",
                    "data_feed_valid",
                    "operator_signal_ready",
                    "operator_score_ready",
                }:
                    new[key] = value
                    continue

                if key not in new:
                    new[key] = value

            new["ticker"] = t
            if price(new) is not None:
                new["price"] = price(new)

            merged[t] = new

    rows = list(merged.values())

    for row in rows:
        p = price(row)
        has_score = n(row.get("final_trade_score")) is not None
        safe_status = str(row.get("score_status") or "").upper()

        if p is None:
            row["operator_status"] = "DATA_FEED_FAIL"
            row["score_status"] = "DATA_FEED_FAIL"
            row["buy_setup_alert_blocked"] = True
            row["alert_eligible"] = False
        elif safe_status in {"ALPACA_AUTH_FAIL", "DATA_FEED_FAIL"} and has_score:
            row["operator_status"] = "WATCH_ONLY"
            row["score_status"] = "WATCH_ONLY"
            row["score_status_corrected_by_operator"] = True
        else:
            row["operator_status"] = row.get("score_status") or "WATCH_ONLY"

        # Hard safety defaults.
        row["order_submission"] = False
        row["live_trading"] = False

    rows.sort(
        key=lambda r: (
            n(r.get("final_trade_score")) if n(r.get("final_trade_score")) is not None else -1,
            n(r.get("runner_potential_score")) if n(r.get("runner_potential_score")) is not None else -1,
            price(r) if price(r) is not None else -1,
        ),
        reverse=True,
    )

    return rows


def run_optional(script: str) -> dict[str, Any]:
    path = Path(script)
    if not path.exists():
        return {"script": script, "status": "SKIPPED", "reason": "missing"}
    try:
        result = subprocess.run(
            [sys.executable, script],
            text=True,
            capture_output=True,
            timeout=120,
        )
        return {
            "script": script,
            "status": "PASS" if result.returncode == 0 else "FAIL",
            "returncode": result.returncode,
            "stdout_tail": result.stdout[-1000:],
            "stderr_tail": result.stderr[-1000:],
        }
    except Exception as exc:
        return {"script": script, "status": "FAIL", "error": str(exc)}


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)

    generated_at = now()

    # Refresh core upstream files, but do not submit orders.
    runs = []
    for script in [
        "scripts/run_alpaca_source_diagnostic.py",
        "scripts/run_scanner_data_source_stabilizer.py",
        "scripts/run_data_feed_truth_guard.py",
        "scripts/run_auth_failure_safe_mode.py",
        "scripts/run_operator_signal_resolver.py",
    ]:
        runs.append(run_optional(script))

    runtime = read_json(INPUTS["runtime"], {})
    safe_mode = read_json(INPUTS["safe_mode"], {})
    alpaca_diag = read_json(INPUTS["alpaca_diag"], {})
    scanner_source = read_json(INPUTS["scanner_source"], {})
    data_guard = read_json(INPUTS["data_guard"], {})
    alerts = read_json(INPUTS["alerts"], {})
    operator_resolver = read_json(INPUTS["operator_resolver"], {})

    rows = merge_rows()

    rows_with_price = sum(1 for r in rows if price(r) is not None)
    rows_with_score = sum(1 for r in rows if n(r.get("final_trade_score")) is not None)
    zero_price_rows = sum(1 for r in rows if price(r) is None)
    trade_eligible = sum(1 for r in rows if str(r.get("score_status") or "").upper().startswith("TRADE"))
    watch_only = sum(1 for r in rows if str(r.get("score_status") or "").upper() == "WATCH_ONLY")

    safe_mode_active = safe_mode.get("safe_mode_active") is True
    trading_auth_ok = alpaca_diag.get("trading_auth_ok") is True
    iex_ok = alpaca_diag.get("iex_data_ok") is True
    sip_ok = alpaca_diag.get("sip_data_ok") is True

    blockers: list[str] = []
    warnings: list[str] = []

    if safe_mode_active:
        blockers.append("safe_mode_active")
    if not trading_auth_ok:
        blockers.append("alpaca_trading_auth_not_ok")
    if not (iex_ok or sip_ok):
        blockers.append("alpaca_data_feed_not_ok")
    if rows_with_price == 0:
        blockers.append("operator_prices_missing")
    if rows_with_score == 0:
        warnings.append("operator_scores_missing")
    if zero_price_rows > 0:
        warnings.append("some_rows_missing_price")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "jini_operator_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "runtime_status": runtime.get("status", "UNKNOWN"),
        "safe_mode_active": safe_mode_active,
        "trading_auth_ok": trading_auth_ok,
        "iex_data_ok": iex_ok,
        "sip_data_ok": sip_ok,
        "rows": len(rows),
        "rows_with_price": rows_with_price,
        "rows_with_score": rows_with_score,
        "zero_price_rows": zero_price_rows,
        "trade_eligible": trade_eligible,
        "watch_only": watch_only,
        "scanner_good_rows": scanner_source.get("current_good_rows"),
        "scanner_bad_rows": scanner_source.get("current_bad_rows"),
        "operator_resolver_status": operator_resolver.get("status"),
        "legacy_data_guard_status": data_guard.get("status"),
        "telegram_configured": alerts.get("telegram_configured"),
        "alert_delivered_count": alerts.get("delivered_count"),
        "order_submission": False,
        "live_trading": False,
        "runs": runs,
    }

    dashboard = {
        "schema_version": "jini_operator_dashboard_v1",
        "generated_at": generated_at,
        "status": status,
        "health": health,
        "rows": rows,
        "safety": {
            "paper_only": True,
            "order_submission": False,
            "live_trading": False,
            "message": "Operator dashboard only. No live trading or order submission.",
        },
    }

    write_json(OUT_DASH, dashboard)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, dashboard)

    print(json.dumps({
        "status": status,
        "rows": len(rows),
        "rows_with_price": rows_with_price,
        "rows_with_score": rows_with_score,
        "blockers": blockers,
        "warnings": warnings,
        "dashboard_path": str(OUT_DASH),
        "health_path": str(OUT_HEALTH),
    }, indent=2))


if __name__ == "__main__":
    main()
