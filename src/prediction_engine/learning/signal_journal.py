from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


SIGNAL_INPUT_CANDIDATES = [
    Path("docs/data/prediction_engine/signal_dashboard_market_guard_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_quality_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_news_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_finra_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard.json"),
    Path("docs/data/prediction_engine/alpaca_paid_market_candidates.json"),
    Path("state/prediction_engine/dynamic_alpaca_candidates.json"),
]

STATE_HISTORY_PATH = Path("state/prediction_engine/signal_history.json")
DOCS_HISTORY_PATH = Path("docs/data/prediction_engine/signal_history.json")
LEARNING_PATH = Path("docs/data/prediction_engine/learning.json")
HEALTH_PATH = Path("docs/data/prediction_engine/signal_journal_health.json")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return default
        return json.loads(raw)
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")


def extract_rows(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        for key in ["rows", "signals", "candidates", "data", "items"]:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

    return []


def load_latest_signals() -> tuple[List[Dict[str, Any]], str]:
    for path in SIGNAL_INPUT_CANDIDATES:
        payload = read_json(path, {})
        rows = extract_rows(payload)
        if rows:
            return rows, str(path)

    return [], "none"


def normalize_signal(row: Dict[str, Any], source_path: str, run_id: str) -> Dict[str, Any]:
    ticker = str(row.get("ticker") or row.get("symbol") or "").upper().strip()

    advanced_quality = row.get("advanced_quality")
    if not isinstance(advanced_quality, dict):
        advanced_quality = {}

    market_guard = row.get("market_guard")
    if not isinstance(market_guard, dict):
        market_guard = {}

    alpaca_news = row.get("alpaca_news")
    if not isinstance(alpaca_news, dict):
        alpaca_news = {}

    return {
        "journal_id": f"{run_id}:{ticker}",
        "journaled_at": run_id,
        "source_path": source_path,
        "ticker": ticker,
        "status": row.get("status") or row.get("signal") or row.get("decision") or "UNKNOWN",
        "score": row.get("score"),
        "price": row.get("price"),
        "entry": row.get("entry"),
        "target": row.get("target"),
        "stop": row.get("stop"),
        "risk_reward": row.get("risk_reward"),
        "relative_volume": row.get("relative_volume"),
        "vwap_distance_pct": (
            row.get("vwap_distance_pct")
            or row.get("vwap_distance_percent")
        ),
        "day_change_pct": (
            row.get("day_change_pct")
            or row.get("day_move_percent")
            or row.get("day_change_percent")
        ),
        "gap_pct": row.get("gap_pct") or row.get("gap_percent"),
        "volume_acceleration": row.get("volume_acceleration"),
        "reason": row.get("reason") or row.get("trade_gate_summary"),
        "quality_gate_status": row.get("quality_gate_status"),
        "quality_gate_blocks": row.get("quality_gate_blocks"),
        "advanced_quality_score": advanced_quality.get("advanced_quality_score"),
        "halt_luld_status": market_guard.get("halt_luld_status"),
        "halt_luld_score": market_guard.get("halt_luld_proxy_score"),
        "news_count": alpaca_news.get("news_count"),
        "news_catalyst_score": alpaca_news.get("news_catalyst_score"),
        "latest_headline": alpaca_news.get("latest_headline"),
        "raw": row,
    }


def dedupe_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    deduped: List[Dict[str, Any]] = []

    for row in rows:
        key = row.get("journal_id")
        if not key:
            key = f"{row.get('journaled_at')}:{row.get('ticker')}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    return deduped


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_status: Dict[str, int] = {}
    by_quality: Dict[str, int] = {}

    for row in rows:
        status = str(row.get("status") or "UNKNOWN")
        by_status[status] = by_status.get(status, 0) + 1

        quality = str(row.get("quality_gate_status") or "UNKNOWN")
        by_quality[quality] = by_quality.get(quality, 0) + 1

    return {
        "total_rows": len(rows),
        "trade_eligible": by_status.get("TRADE_ELIGIBLE", 0),
        "trade_eligible_count": by_status.get("TRADE_ELIGIBLE", 0),
        "no_trade": by_status.get("NO_TRADE", 0),
        "no_trade_count": by_status.get("NO_TRADE", 0),
        "by_status": by_status,
        "by_quality_gate": by_quality,
    }


def run_signal_journal() -> Dict[str, Any]:
    run_id = now_utc_iso()
    current_rows, source_path = load_latest_signals()

    existing_payload = read_json(STATE_HISTORY_PATH, {})
    existing_rows = extract_rows(existing_payload)

    new_rows = [
        normalize_signal(row, source_path, run_id)
        for row in current_rows
        if str(row.get("ticker") or row.get("symbol") or "").strip()
    ]

    combined_rows = dedupe_rows(existing_rows + new_rows)

    # Keep the file from growing forever.
    max_rows = 5000
    if len(combined_rows) > max_rows:
        combined_rows = combined_rows[-max_rows:]

    summary = summarize(combined_rows)

    payload = {
        "schema_version": "signal_journal_v2",
        "generated_at": run_id,
        "status": "PASS" if new_rows else "WARN",
        "source_path": source_path,
        "current_signal_count": len(current_rows),
        "new_rows_added": len(new_rows),
        "summary": summary,
        "rows": combined_rows,
        "safety": {
            "paper_only": True,
            "order_submission": False,
            "journal_only": True,
            "disclaimer": "Signal journal only. Not financial advice.",
        },
    }

    learning_payload = {
        "schema_version": "learning_summary_v2",
        "generated_at": run_id,
        "status": payload["status"],
        "source_path": source_path,
        "summary": summary,
        "rows": combined_rows[-500:],
        "safety": payload["safety"],
    }

    health = {
        "schema_version": "signal_journal_health_v2",
        "generated_at": run_id,
        "status": payload["status"],
        "message": (
            "signals journaled"
            if new_rows
            else "no signals found to journal"
        ),
        "source_path": source_path,
        "current_signal_count": len(current_rows),
        "new_rows_added": len(new_rows),
        "journal_rows": len(combined_rows),
        "trade_eligible_count": summary["trade_eligible_count"],
        "no_trade_count": summary["no_trade_count"],
        "paper_only": True,
        "order_submission": False,
    }

    write_json(STATE_HISTORY_PATH, payload)
    write_json(DOCS_HISTORY_PATH, payload)
    write_json(LEARNING_PATH, learning_payload)
    write_json(HEALTH_PATH, health)

    return {
        "status": payload["status"],
        "source_path": source_path,
        "current_signal_count": len(current_rows),
        "new_rows_added": len(new_rows),
        "journal_rows": len(combined_rows),
        "health_path": str(HEALTH_PATH),
        "learning_path": str(LEARNING_PATH),
    }


def main() -> None:
    print(json.dumps(run_signal_journal(), indent=2))


if __name__ == "__main__":
    main()
