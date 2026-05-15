from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


FREE_SCANNER_PATH = Path("docs/data/prediction_engine/free_scanner.json")
SIGNAL_DASHBOARD_PATH = Path("docs/data/prediction_engine/signal_dashboard.json")
SOCIAL_SENTIMENT_PATH = Path("docs/data/prediction_engine/social_sentiment.json")


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    try:
        raw = path.read_text(encoding="utf-8").strip()
        return json.loads(raw) if raw else default
    except Exception:
        return default


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=False), encoding="utf-8")


def _signal_label(status: str) -> Dict[str, str]:
    if status == "TRADE_ELIGIBLE":
        return {
            "signal": "TRADE ELIGIBLE",
            "color": "green",
            "meaning": "Strongest paper-trade candidate. Still paper-only.",
            "action": "Eligible for future paper gate only if all risk checks pass.",
        }

    if status == "WAIT_FOR_PULLBACK":
        return {
            "signal": "WAIT FOR PULLBACK",
            "color": "orange",
            "meaning": "Good setup, but entry is extended.",
            "action": "Dashboard only. Do not chase.",
        }

    if status == "ALERT_ONLY":
        return {
            "signal": "ALERT ONLY",
            "color": "blue",
            "meaning": "Interesting, but missing at least one key confirmation.",
            "action": "Track for confirmation.",
        }

    if status == "WATCH_ONLY":
        return {
            "signal": "WATCH ONLY",
            "color": "yellow",
            "meaning": "Early or incomplete setup.",
            "action": "Watch only. No order.",
        }

    return {
        "signal": "NO TRADE",
        "color": "red",
        "meaning": "Blocked by risk, data, trend, or score rules.",
        "action": "No new entry.",
    }


def build_dashboard_payload() -> Dict[str, Any]:
    scanner = _read_json(FREE_SCANNER_PATH, {})

    rows = scanner.get("rows")
    if not isinstance(rows, list):
        rows = []

    dashboard_rows: List[Dict[str, Any]] = []

    for item in rows:
        if not isinstance(item, dict):
            continue

        status = str(item.get("status") or "NO_TRADE")
        label = _signal_label(status)
        data_quality = item.get("data_quality") if isinstance(item.get("data_quality"), dict) else {}

        dashboard_rows.append(
            {
                "ticker": item.get("ticker"),
                "source_type": item.get("source_type", "free_scanner_normalizer"),
                "signal": label["signal"],
                "status": status,
                "signal_color": label["color"],
                "meaning": label["meaning"],
                "action": label["action"],
                "score": item.get("score"),
                "price": item.get("price"),
                "entry": item.get("entry"),
                "stop": item.get("stop"),
                "target": item.get("target"),
                "risk_reward": item.get("risk_reward"),
                "relative_volume": item.get("relative_volume"),
                "day_move_percent": item.get("day_change_pct"),
                "gap_pct": item.get("gap_pct"),
                "vwap": item.get("vwap"),
                "vwap_distance_percent": item.get("vwap_distance_pct"),
                "volume_acceleration": item.get("volume_acceleration"),
                "trend_state": item.get("trend_state"),
                "candidate_quality": data_quality.get("quality", "UNKNOWN"),
                "data_quality": data_quality,
                "trade_gate_summary": item.get("reason"),
                "no_trade_reasons": item.get("no_trade_reasons") or [],
            }
        )

    counts = {
        "total": len(dashboard_rows),
        "trade_eligible": sum(1 for row in dashboard_rows if row["status"] == "TRADE_ELIGIBLE"),
        "wait_for_pullback": sum(1 for row in dashboard_rows if row["status"] == "WAIT_FOR_PULLBACK"),
        "alert_only": sum(1 for row in dashboard_rows if row["status"] == "ALERT_ONLY"),
        "watch_only": sum(1 for row in dashboard_rows if row["status"] == "WATCH_ONLY"),
        "no_trade": sum(1 for row in dashboard_rows if row["status"] == "NO_TRADE"),
        "real_rows": scanner.get("counts", {}).get("real_rows", 0),
        "placeholder_rows": scanner.get("counts", {}).get("placeholder_rows", 0),

        # Legacy-friendly names for older dashboard cards.
        "buy_watch": sum(1 for row in dashboard_rows if row["status"] == "TRADE_ELIGIBLE"),
        "strong_watch": sum(1 for row in dashboard_rows if row["status"] == "ALERT_ONLY"),
        "track_only": sum(
            1 for row in dashboard_rows
            if row["status"] in {"WATCH_ONLY", "WAIT_FOR_PULLBACK"}
        ),
        "avoid_sell_risk": sum(1 for row in dashboard_rows if row["status"] == "NO_TRADE"),
    }

    payload = {
        "schema_version": "signal_dashboard_free_scanner_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "rows": dashboard_rows,
        "counts": counts,
        "scanner_summary": {
            "candidate_count": scanner.get("counts", {}).get("total", 0),
            "real_rows": scanner.get("counts", {}).get("real_rows", 0),
            "placeholder_rows": scanner.get("counts", {}).get("placeholder_rows", 0),
            "trade_eligible_count": scanner.get("counts", {}).get("trade_eligible", 0),
            "used_placeholders": scanner.get("used_placeholders", False),
            "sources_used": scanner.get("sources_used", []),
        },
        "best_trade_eligible": scanner.get("best_trade_eligible"),
        "safety": {
            "paper_only": True,
            "order_submission": False,
            "live_trading": False,
            "free_api_only": True,
            "allowed_to_trade_status": "TRADE_ELIGIBLE",
            "disclaimer": "Research labels only. Not financial advice.",
        },
    }

    return payload


def build_social_placeholder(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "schema_version": "social_placeholder_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "provider_policy": {
            "x": "disabled by default",
            "stocktwits": "disabled by default",
            "reddit": "disabled by default",
        },
        "rows": [
            {
                "ticker": row.get("ticker"),
                "overall_sentiment": "not_connected",
                "buzz_level": "not_connected",
                "note": "Social layer is intentionally disabled in Package 1A.",
            }
            for row in rows[:20]
        ],
        "safety": {
            "no_scraping": True,
            "llm_calls": 0,
            "order_submission": False,
        },
    }


def export_dashboard() -> Dict[str, Any]:
    payload = build_dashboard_payload()
    social = build_social_placeholder(payload["rows"])

    _write_json(SIGNAL_DASHBOARD_PATH, payload)
    _write_json(SOCIAL_SENTIMENT_PATH, social)

    return {
        "status": "PASS",
        "output_path": str(SIGNAL_DASHBOARD_PATH),
        "social_output_path": str(SOCIAL_SENTIMENT_PATH),
        "row_count": len(payload["rows"]),
        "counts": payload["counts"],
    }


def main() -> None:
    print(json.dumps(export_dashboard(), indent=2))


if __name__ == "__main__":
    main()
