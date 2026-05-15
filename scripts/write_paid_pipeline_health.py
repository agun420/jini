from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


OUTPUT_DOCS = Path("docs/data/prediction_engine/master_paid_pipeline_health.json")
OUTPUT_STATE = Path("state/prediction_engine/master_paid_pipeline_state.json")


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
    path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")


def status_of(path: str) -> dict:
    p = Path(path)
    payload = read_json(p, {})
    return {
        "path": path,
        "exists": p.exists(),
        "status": payload.get("status") if isinstance(payload, dict) else None,
        "generated_at": payload.get("generated_at") if isinstance(payload, dict) else None,
    }


def main() -> None:
    checks = [
        "docs/data/prediction_engine/alpaca_market_scanner_health.json",
        "docs/data/prediction_engine/scanner_health.json",
        "docs/data/prediction_engine/sec_catalyst_health.json",
        "docs/data/prediction_engine/finra_short_pressure_health.json",
        "docs/data/prediction_engine/alpaca_news_health.json",
        "docs/data/prediction_engine/advanced_signal_quality_health.json",
        "docs/data/prediction_engine/halt_luld_circuit_guard_health.json",
        "docs/data/prediction_engine/signal_journal_health.json",
        "docs/data/prediction_engine/outcome_labeler_health.json",
        "docs/data/prediction_engine/adaptive_guard_health.json",
        "docs/data/prediction_engine/paper_execution_gate_health.json",
        "docs/data/prediction_engine/slippage_fill_tracker_health.json",
        "docs/data/prediction_engine/real_money_readiness_guard_health.json",
    ]

    layer_status = [status_of(path) for path in checks]
    critical = [
        item for item in layer_status
        if item["path"] in {
            "docs/data/prediction_engine/alpaca_market_scanner_health.json",
            "docs/data/prediction_engine/scanner_health.json",
        }
    ]

    critical_ok = all(item["exists"] for item in critical)

    payload = {
        "schema_version": "master_paid_pipeline_health_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if critical_ok else "WARN",
        "mode": "paid_alpaca_elite_pipeline",
        "critical_ok": critical_ok,
        "layers": layer_status,
        "safety": {
            "paper_only": True,
            "order_submission_default": False,
            "live_trading": False,
        },
    }

    write_json(OUTPUT_DOCS, payload)
    write_json(OUTPUT_STATE, payload)

    print(json.dumps({
        "status": payload["status"],
        "output": str(OUTPUT_DOCS),
        "critical_ok": critical_ok,
    }, indent=2))


if __name__ == "__main__":
    main()
