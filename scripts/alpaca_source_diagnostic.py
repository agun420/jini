from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DOCS_DIR = Path("docs/data/prediction_engine")
STATE_DIR = Path("state/prediction_engine")

OUT_DOCS = DOCS_DIR / "alpaca_source_diagnostic.json"
OUT_HEALTH = DOCS_DIR / "alpaca_source_diagnostic_health.json"
OUT_STATE = STATE_DIR / "alpaca_source_diagnostic.json"

SCANNER_FILES = [
    DOCS_DIR / "signal_dashboard.json",
    DOCS_DIR / "signal_dashboard_stable.json",
    DOCS_DIR / "signal_dashboard_data_guard_enriched.json",
    DOCS_DIR / "signal_dashboard_rvol_enriched.json",
    DOCS_DIR / "scanner_data_source_health.json",
    DOCS_DIR / "data_feed_quality_health.json",
]


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


def f(value: Any) -> float | None:
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
        value = f(row.get(key))
        if value is not None:
            return value
    return None


def safe_error(exc: Exception) -> dict[str, Any]:
    text = str(exc)
    lowered = text.lower()
    reason = "unknown_error"

    if "401" in text or "authorization" in lowered or "unauthorized" in lowered:
        reason = "alpaca_auth_failed_401"
    elif "subscription" in lowered or "permit" in lowered or "forbidden" in lowered or "403" in text:
        reason = "alpaca_feed_permission_failed"
    elif "timeout" in lowered:
        reason = "alpaca_timeout"
    elif "name or service not known" in lowered or "temporary failure" in lowered:
        reason = "network_dns_failure"

    return {
        "ok": False,
        "reason": reason,
        "error_type": type(exc).__name__,
        "error": text[:500],
    }


def env_check() -> dict[str, Any]:
    keys = {
        "ALPACA_API_KEY": os.getenv("ALPACA_API_KEY"),
        "ALPACA_SECRET_KEY": os.getenv("ALPACA_SECRET_KEY"),
        "APCA_API_KEY_ID": os.getenv("APCA_API_KEY_ID"),
        "APCA_API_SECRET_KEY": os.getenv("APCA_API_SECRET_KEY"),
        "ALPACA_DATA_FEED": os.getenv("ALPACA_DATA_FEED"),
    }

    def redacted(value: str | None) -> dict[str, Any]:
        return {
            "exists": bool(value),
            "length": len(value) if value else 0,
            "starts_with": value[:4] if value else None,
            "ends_with": value[-4:] if value else None,
            "has_spaces": (" " in value) if value else None,
            "is_placeholder": value in {"YOUR_KEY", "YOUR_SECRET", "YOUR_ALPACA_KEY", "YOUR_ALPACA_SECRET"},
        }

    return {name: redacted(value) for name, value in keys.items()}


def test_trading_auth() -> dict[str, Any]:
    try:
        from alpaca.trading.client import TradingClient

        key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
        secret = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")

        if not key or not secret:
            return {"ok": False, "reason": "missing_key_or_secret"}

        client = TradingClient(key, secret, paper=True)
        account = client.get_account()

        return {
            "ok": True,
            "account_status": str(getattr(account, "status", "UNKNOWN")),
            "paper": True,
            "cash_present": bool(getattr(account, "cash", None)),
        }
    except Exception as exc:
        return safe_error(exc)


def test_data_feed(feed_name: str) -> dict[str, Any]:
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.data.enums import DataFeed

        key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
        secret = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")

        if not key or not secret:
            return {"ok": False, "reason": "missing_key_or_secret", "feed": feed_name}

        feed = DataFeed.IEX if feed_name.upper() == "IEX" else DataFeed.SIP
        client = StockHistoricalDataClient(key, secret)

        end = datetime.now(timezone.utc) - timedelta(minutes=20)
        start = end - timedelta(minutes=30)

        bars_result: dict[str, Any] = {"ok": False}
        quote_result: dict[str, Any] = {"ok": False}

        try:
            bars = client.get_stock_bars(StockBarsRequest(
                symbol_or_symbols=["AAPL", "MSFT"],
                timeframe=TimeFrame.Minute,
                start=start,
                end=end,
                feed=feed,
            ))
            bar_rows = bars.data
            bars_result = {
                "ok": True,
                "symbols": {
                    sym: {
                        "bars": len(rows),
                        "last_close": rows[-1].close if rows else None,
                    }
                    for sym, rows in bar_rows.items()
                },
            }
        except Exception as exc:
            bars_result = safe_error(exc)

        try:
            quotes = client.get_stock_latest_quote(StockLatestQuoteRequest(
                symbol_or_symbols=["AAPL", "MSFT"],
                feed=feed,
            ))
            quote_result = {
                "ok": True,
                "symbols": {
                    sym: {
                        "bid": getattr(q, "bid_price", None),
                        "ask": getattr(q, "ask_price", None),
                    }
                    for sym, q in quotes.items()
                },
            }
        except Exception as exc:
            quote_result = safe_error(exc)

        return {
            "feed": feed_name.upper(),
            "bars": bars_result,
            "quotes": quote_result,
            "ok": bool(bars_result.get("ok") or quote_result.get("ok")),
        }
    except Exception as exc:
        out = safe_error(exc)
        out["feed"] = feed_name.upper()
        return out


def scanner_file_summary() -> dict[str, Any]:
    summary: dict[str, Any] = {}

    for path in SCANNER_FILES:
        payload = read_json(path, {})
        rows = rows_from(payload)

        zero_price = 0
        good_price = 0
        missing_price = 0
        statuses: dict[str, int] = {}

        for row in rows:
            p = price(row)
            if p is None:
                missing_price += 1
            elif p <= 0:
                zero_price += 1
            else:
                good_price += 1

            status = str(row.get("score_status") or row.get("status") or "UNKNOWN")
            statuses[status] = statuses.get(status, 0) + 1

        summary[str(path)] = {
            "exists": path.exists(),
            "top_level_status": payload.get("status") if isinstance(payload, dict) else None,
            "rows": len(rows),
            "good_price_rows": good_price,
            "zero_price_rows": zero_price,
            "missing_price_rows": missing_price,
            "statuses": statuses,
        }

    return summary


def export() -> dict[str, Any]:
    generated_at = now()

    env = env_check()
    trading = test_trading_auth()
    data_iex = test_data_feed("IEX")
    data_sip = test_data_feed("SIP")
    scanner = scanner_file_summary()

    blockers: list[str] = []
    warnings: list[str] = []

    has_key = env["ALPACA_API_KEY"]["exists"] or env["APCA_API_KEY_ID"]["exists"]
    has_secret = env["ALPACA_SECRET_KEY"]["exists"] or env["APCA_API_SECRET_KEY"]["exists"]

    if not has_key:
        blockers.append("alpaca_key_missing")
    if not has_secret:
        blockers.append("alpaca_secret_missing")

    if trading.get("reason") == "alpaca_auth_failed_401":
        blockers.append("alpaca_trading_auth_failed_401")

    if data_iex.get("ok") is not True and data_sip.get("ok") is not True:
        blockers.append("all_alpaca_data_feed_tests_failed")

    for feed_result in (data_iex, data_sip):
        for part in ("bars", "quotes"):
            result = feed_result.get(part, {})
            reason = result.get("reason")
            if reason and reason not in warnings:
                warnings.append(reason)

    base = scanner.get(str(DOCS_DIR / "signal_dashboard.json"), {})
    if base.get("zero_price_rows", 0) > 0:
        warnings.append("base_signal_dashboard_has_zero_price_rows")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    payload = {
        "schema_version": "alpaca_source_diagnostic_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "env": env,
        "trading_auth": trading,
        "data_feeds": {
            "IEX": data_iex,
            "SIP": data_sip,
        },
        "scanner_files": scanner,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "purpose": "Diagnostic only. Does not submit orders.",
        },
    }

    health = {
        "schema_version": "alpaca_source_diagnostic_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "trading_auth_ok": trading.get("ok") is True,
        "iex_data_ok": data_iex.get("ok") is True,
        "sip_data_ok": data_sip.get("ok") is True,
        "order_submission": False,
        "live_trading": False,
    }

    write_json(OUT_DOCS, payload)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, payload)

    return {
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "trading_auth_ok": health["trading_auth_ok"],
        "iex_data_ok": health["iex_data_ok"],
        "sip_data_ok": health["sip_data_ok"],
        "health_path": str(OUT_HEALTH),
        "diagnostic_path": str(OUT_DOCS),
    }


def main() -> None:
    print(json.dumps(export(), indent=2))


if __name__ == "__main__":
    main()
