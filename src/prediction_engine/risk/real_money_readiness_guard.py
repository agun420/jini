from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


ADAPTIVE_GUARD_PATH = Path("docs/data/prediction_engine/adaptive_guard.json")
PAPER_ORDER_PLAN_PATH = Path("docs/data/prediction_engine/paper_order_plan.json")
OUTCOMES_PATH = Path("docs/data/prediction_engine/outcomes.json")
QUALITY_PATH = Path("docs/data/prediction_engine/advanced_signal_quality.json")

OUTPUT_DOCS_PATH = Path("docs/data/prediction_engine/real_money_readiness_guard.json")
OUTPUT_STATE_PATH = Path("state/prediction_engine/real_money_readiness_guard.json")
HEALTH_PATH = Path("docs/data/prediction_engine/real_money_readiness_guard_health.json")


def now_utc_iso() -> str:
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
    path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def extract_rows(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "signals", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def outcome_strength(outcomes: Dict[str, Any]) -> Dict[str, Any]:
    summary = outcomes.get("summary") if isinstance(outcomes.get("summary"), dict) else {}
    rows = extract_rows(outcomes)

    labels = summary.get("outcomes_by_label") if isinstance(summary.get("outcomes_by_label"), dict) else {}
    wins = int(labels.get("TARGET_BEFORE_STOP", 0) or 0)
    losses = int(labels.get("STOP_BEFORE_TARGET", 0) or 0)
    usable = wins + losses
    win_rate = wins / usable if usable else None

    avg_return = safe_float(summary.get("average_close_return_pct"))
    return_count = int(summary.get("return_observation_count") or 0)

    return {
        "usable_outcomes": usable,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 4) if win_rate is not None else None,
        "average_close_return_pct": avg_return,
        "return_observation_count": return_count,
        "row_count": len(rows),
    }


def quality_strength(quality: Dict[str, Any]) -> Dict[str, Any]:
    counts = quality.get("counts") if isinstance(quality.get("counts"), dict) else {}
    approved = int(counts.get("quality_approved") or 0)
    blocked = int(counts.get("quality_blocked") or 0)
    signals = int(counts.get("signals") or 0)
    return {
        "signals": signals,
        "quality_approved": approved,
        "quality_blocked": blocked,
        "approved_rate": round(approved / signals, 4) if signals else None,
    }


def _get_settings() -> Dict[str, Any]:
    account_type = os.getenv("ACCOUNT_TYPE", "unknown").lower().strip()
    if account_type not in {"cash", "margin", "unknown"}:
        account_type = "unknown"

    return {
        "account_type": account_type,
        "manual_approval_required": os.getenv("MANUAL_APPROVAL_REQUIRED", "true").lower() == "true",
        "engine_kill_switch": os.getenv("ENGINE_KILL_SWITCH", "false").lower() == "true",
        "daily_loss_cap": safe_float(os.getenv("DAILY_LOSS_CAP_DOLLARS"), 150.0) or 150.0,
        "max_real_trade_notional": safe_float(os.getenv("MAX_REAL_TRADE_NOTIONAL"), 250.0) or 250.0,
        "min_paper_outcomes_before_real": int(os.getenv("MIN_PAPER_OUTCOMES_BEFORE_REAL", "50")),
        "settled_cash": safe_float(os.getenv("SETTLED_CASH")),
    }


def _calculate_open_unrealized(positions: List[Any]) -> float:
    open_unrealized = 0.0
    for pos in positions:
        if isinstance(pos, dict):
            open_unrealized += safe_float(pos.get("unrealized_pl"), 0.0) or 0.0
    return open_unrealized


def _evaluate_rules(
    settings: Dict[str, Any],
    guard: Dict[str, Any],
    order_plan: Dict[str, Any],
    plan: Dict[str, Any],
    outcome_stats: Dict[str, Any],
    quality_stats: Dict[str, Any],
    open_unrealized: float,
) -> tuple[List[str], List[str]]:
    blocks: List[str] = []
    warnings: List[str] = []

    if settings["engine_kill_switch"]:
        blocks.append("engine_kill_switch_enabled")

    if settings["manual_approval_required"]:
        blocks.append("manual_approval_required_for_real_money")

    if settings["account_type"] == "unknown":
        blocks.append("account_type_unknown")
    elif settings["account_type"] == "cash":
        # Alpaca paper account may not expose true settled cash cleanly.
        # For real cash trading, block unless explicitly supplied.
        if settings["settled_cash"] is None:
            blocks.append("cash_account_settled_cash_unknown_t1_guard")
        elif settings["settled_cash"] < settings["max_real_trade_notional"]:
            blocks.append("settled_cash_below_max_real_trade_notional")
    elif settings["account_type"] == "margin":
        warnings.append("margin_account_requires_intraday_margin_monitoring")

    if guard.get("allow_new_entries") is False:
        blocks.append("adaptive_guard_blocks_new_entries")

    if guard.get("risk_mode") in {"DEFENSIVE", "PAUSED"}:
        blocks.append(f"adaptive_guard_risk_mode_{guard.get('risk_mode')}")

    if not order_plan.get("created"):
        warnings.append("no_current_paper_order_plan_created")

    if plan.get("submission", {}).get("submitted"):
        warnings.append("paper_order_submission_detected_review_required")

    if outcome_stats["usable_outcomes"] < settings["min_paper_outcomes_before_real"]:
        blocks.append("not_enough_paper_outcomes_for_real_money")

    if outcome_stats["win_rate"] is not None and outcome_stats["win_rate"] < 0.45:
        blocks.append("paper_outcome_win_rate_below_45_percent")

    if outcome_stats["average_close_return_pct"] is not None and outcome_stats["average_close_return_pct"] < 0:
        warnings.append("average_close_return_negative")

    if quality_stats["quality_approved"] == 0:
        warnings.append("no_quality_approved_signals")

    if open_unrealized <= -abs(settings["daily_loss_cap"]):
        blocks.append("open_unrealized_loss_exceeds_daily_loss_cap")

    return blocks, warnings


def build_readiness() -> Dict[str, Any]:
    adaptive = read_json(ADAPTIVE_GUARD_PATH, {})
    plan = read_json(PAPER_ORDER_PLAN_PATH, {})
    outcomes = read_json(OUTCOMES_PATH, {})
    quality = read_json(QUALITY_PATH, {})

    settings = _get_settings()

    guard = adaptive.get("guard") if isinstance(adaptive.get("guard"), dict) else {}
    order_plan = plan.get("order_plan") if isinstance(plan.get("order_plan"), dict) else {}
    account_snapshot = plan.get("account_snapshot") if isinstance(plan.get("account_snapshot"), dict) else {}

    outcome_stats = outcome_strength(outcomes)
    quality_stats = quality_strength(quality)

    positions = plan.get("positions") if isinstance(plan.get("positions"), list) else []
    open_unrealized = _calculate_open_unrealized(positions)

    blocks, warnings = _evaluate_rules(
        settings=settings,
        guard=guard,
        order_plan=order_plan,
        plan=plan,
        outcome_stats=outcome_stats,
        quality_stats=quality_stats,
        open_unrealized=open_unrealized,
    )

    readiness_status = "NOT_READY"
    if not blocks:
        readiness_status = "PILOT_READY_MANUAL_ONLY"
        warnings.append("real_money_pilot_must_start_tiny_and_manual")

    payload = {
        "schema_version": "real_money_readiness_guard_v1",
        "generated_at": now_utc_iso(),
        "status": "PASS",
        "readiness_status": readiness_status,
        "blocks": blocks,
        "warnings": warnings,
        "settings": {
            "account_type": settings["account_type"],
            "manual_approval_required": settings["manual_approval_required"],
            "engine_kill_switch": settings["engine_kill_switch"],
            "daily_loss_cap_dollars": settings["daily_loss_cap"],
            "max_real_trade_notional": settings["max_real_trade_notional"],
            "min_paper_outcomes_before_real": settings["min_paper_outcomes_before_real"],
        },
        "adaptive_guard": {
            "risk_mode": guard.get("risk_mode"),
            "allow_new_entries": guard.get("allow_new_entries"),
            "min_score_required": guard.get("min_score_required"),
        },
        "account_snapshot": {
            "available": account_snapshot.get("available"),
            "buying_power": account_snapshot.get("buying_power"),
            "cash": account_snapshot.get("cash"),
            "equity": account_snapshot.get("equity"),
            "open_unrealized_pl_estimate": round(open_unrealized, 2),
        },
        "outcome_strength": outcome_stats,
        "quality_strength": quality_stats,
        "safety": {
            "live_trading_enabled": False,
            "real_money_automation_enabled": False,
            "manual_approval_required": True,
            "purpose": "Readiness assessment only. Does not submit orders.",
            "disclaimer": "Risk guard only. Not financial advice.",
        },
    }

    return payload


def export_readiness() -> Dict[str, Any]:
    payload = build_readiness()
    health = {
        "schema_version": "real_money_readiness_guard_health_v1",
        "generated_at": payload["generated_at"],
        "status": payload["status"],
        "readiness_status": payload["readiness_status"],
        "block_count": len(payload["blocks"]),
        "warning_count": len(payload["warnings"]),
        "live_trading_enabled": False,
        "real_money_automation_enabled": False,
    }
    write_json(OUTPUT_DOCS_PATH, payload)
    write_json(OUTPUT_STATE_PATH, payload)
    write_json(HEALTH_PATH, health)
    return {
        "status": "PASS",
        "readiness_status": payload["readiness_status"],
        "blocks": payload["blocks"],
        "output_path": str(OUTPUT_DOCS_PATH),
        "health_path": str(HEALTH_PATH),
    }


def main() -> None:
    print(json.dumps(export_readiness(), indent=2))


if __name__ == "__main__":
    main()
