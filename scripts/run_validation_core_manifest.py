from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

OUT_DOCS = DOCS / "validation_core_manifest.json"
OUT_HEALTH = DOCS / "validation_core_manifest_health.json"
OUT_STATE = STATE / "validation_core_manifest.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    generated_at = now()

    modules = {
        "trade_journal": {
            "path": "src/prediction_engine/learning/trade_journal.py",
            "purpose": "Track simulated/paper trade records and closed outcomes.",
            "status": "PLANNED",
            "can_place_orders": False,
            "can_change_config": False,
        },
        "blocked_journal": {
            "path": "src/prediction_engine/learning/blocked_journal.py",
            "purpose": "Track blocked buy-order alerts and measure missed gains or saved losses.",
            "status": "PLANNED",
            "can_place_orders": False,
            "can_change_config": False,
        },
        "asymmetric_slippage": {
            "path": "src/prediction_engine/execution/asymmetric_slip.py",
            "purpose": "Model chart fill, realistic fill, worst-case fill, spread, volatility, and ATR-bounded slippage.",
            "status": "PLANNED",
            "can_place_orders": False,
            "can_change_config": False,
        },
        "forward_validator": {
            "path": "src/prediction_engine/optimization/forward_validator.py",
            "purpose": "Run purged forward validation and export suggested_config.json only after enough closed outcomes exist.",
            "status": "PLANNED",
            "can_place_orders": False,
            "can_change_config": False,
        },
    }

    hard_rules = [
        "Validation core is research-only.",
        "No module can submit orders.",
        "No module can enable live trading.",
        "No module can overwrite runtime config automatically.",
        "Forward validator must require at least 30 closed trade events before suggesting config changes.",
        "Paper auto-trade remains blocked until 100+ live alert outcomes and 500+ validated setup tests exist.",
        "Live trading remains blocked until separate manual approval.",
    ]

    outputs = {
        "trade_journal": {
            "state": "state/prediction_engine/trade_journal.json",
            "health": "docs/data/prediction_engine/trade_journal_health.json",
        },
        "blocked_journal": {
            "state": "state/prediction_engine/blocked_journal.json",
            "health": "docs/data/prediction_engine/blocked_journal_health.json",
        },
        "slippage_quality": {
            "state": "state/prediction_engine/slippage_quality.json",
            "health": "docs/data/prediction_engine/slippage_quality_health.json",
        },
        "forward_validation": {
            "state": "state/prediction_engine/forward_validation.json",
            "health": "docs/data/prediction_engine/forward_validation_health.json",
            "suggested_config": "state/prediction_engine/suggested_config.json",
        },
        "validation_status": {
            "docs": "docs/data/prediction_engine/validation_status.json",
        },
    }

    health = {
        "schema_version": "validation_core_manifest_health_v1",
        "generated_at": generated_at,
        "status": "PASS",
        "blockers": [],
        "warnings": [],
        "module_count": len(modules),
        "validation_core_ready_to_build": True,
        "trade_journal_ready": False,
        "blocked_journal_ready": False,
        "slippage_model_ready": False,
        "forward_validator_ready": False,
        "paper_auto_trade_ready": False,
        "auto_trade_ready": False,
        "live_trade_ready": False,
        "order_submission": False,
        "live_trading": False,
        "message": "Validation core manifest installed. Modules are planned but not yet active.",
    }

    payload = {
        "schema_version": "validation_core_manifest_v1",
        "generated_at": generated_at,
        "mission": "Closed-loop validation core for Jini. Prove edge before changing parameters or enabling paper automation.",
        "phase": "Phase 9A - Closed-Loop Validation Core",
        "health": health,
        "modules": modules,
        "outputs": outputs,
        "hard_rules": hard_rules,
        "build_order": [
            "Package 54 - Trade Journal Core",
            "Package 55 - Blocked Alert Journal",
            "Package 56 - Asymmetric Slippage Audit",
            "Package 57 - Forward Validation Optimizer",
            "Package 58 - Validation Dashboard Panel",
            "Package 59 - Auto-Trade Readiness Re-Audit",
        ],
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "auto_config_overwrite": False,
            "purpose": "Research and validation only.",
        },
    }

    write_json(OUT_DOCS, payload)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, payload)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
