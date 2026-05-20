from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

OPERATOR_HEALTH = DOCS / "operator_health.json"
STABILITY_HEALTH = DOCS / "operator_stability_health.json"
FINAL_AUDIT = DOCS / "final_repo_audit.json"
PRICE_REGIME_HEALTH = DOCS / "price_regime_focused_validation_health.json"
SCORE_V2_HEALTH = DOCS / "score_v2_research_health.json"
BUY_ALERT_HEALTH = DOCS / "buy_order_alert_mode_health.json"
FEED_STATUS = DOCS / "feed_status_health.json"

VALIDATION_STATUS = DOCS / "validation_status_health.json"
VALIDATION_MANIFEST = DOCS / "validation_core_manifest_health.json"
TRADE_JOURNAL = DOCS / "trade_journal_health.json"
BLOCKED_JOURNAL = DOCS / "blocked_journal_health.json"
SLIPPAGE_HEALTH = DOCS / "slippage_quality_health.json"
FORWARD_VALIDATION = DOCS / "forward_validation_health.json"
ALERT_OUTCOME = DOCS / "buy_order_alert_outcome_journal_health.json"

OUT_DOCS = DOCS / "auto_trade_readiness_audit.json"
OUT_HEALTH = DOCS / "auto_trade_readiness_health.json"
OUT_STATE = STATE / "auto_trade_readiness_audit.json"


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


def f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def i(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def add_if(condition: bool, target: list[str], reason: str) -> None:
    if condition and reason not in target:
        target.append(reason)


def main() -> None:
    generated_at = now()

    operator = read_json(OPERATOR_HEALTH, {})
    stability = read_json(STABILITY_HEALTH, {})
    final_audit = read_json(FINAL_AUDIT, {})
    final_score = final_audit.get("score", {}) if isinstance(final_audit, dict) else {}
    regime = read_json(PRICE_REGIME_HEALTH, {})
    score_v2 = read_json(SCORE_V2_HEALTH, {})
    buy_alert = read_json(BUY_ALERT_HEALTH, {})
    feed_status = read_json(FEED_STATUS, {})

    validation_status = read_json(VALIDATION_STATUS, {})
    validation_manifest = read_json(VALIDATION_MANIFEST, {})
    trade_journal = read_json(TRADE_JOURNAL, {})
    blocked_journal = read_json(BLOCKED_JOURNAL, {})
    slippage = read_json(SLIPPAGE_HEALTH, {})
    forward = read_json(FORWARD_VALIDATION, {})
    outcome = read_json(ALERT_OUTCOME, {})

    warnings: list[str] = []
    buy_order_alert_blockers: list[str] = []
    paper_auto_trade_blockers: list[str] = []
    auto_trade_blockers: list[str] = []
    live_trade_blockers: list[str] = []

    # Core repo/runtime safety checks.
    add_if(operator.get("status") not in {"PASS", "WARN"}, buy_order_alert_blockers, "operator_health_not_pass_or_warn")
    add_if(operator.get("status") not in {"PASS", "WARN"}, paper_auto_trade_blockers, "operator_health_not_pass_or_warn")
    add_if(operator.get("status") not in {"PASS", "WARN"}, auto_trade_blockers, "operator_health_not_pass_or_warn")
    add_if(operator.get("status") not in {"PASS", "WARN"}, live_trade_blockers, "operator_health_not_pass_or_warn")

    add_if(bool(stability.get("blockers")), buy_order_alert_blockers, "operator_stability_has_blockers")
    add_if(bool(stability.get("blockers")), paper_auto_trade_blockers, "operator_stability_has_blockers")
    add_if(bool(stability.get("blockers")), auto_trade_blockers, "operator_stability_has_blockers")
    add_if(bool(stability.get("blockers")), live_trade_blockers, "operator_stability_has_blockers")

    add_if(final_audit.get("status") != "PASS" or final_score.get("score") != 100, buy_order_alert_blockers, "final_repo_audit_not_100")
    add_if(final_audit.get("status") != "PASS" or final_score.get("score") != 100, paper_auto_trade_blockers, "final_repo_audit_not_100")
    add_if(final_audit.get("status") != "PASS" or final_score.get("score") != 100, auto_trade_blockers, "final_repo_audit_not_100")
    add_if(final_audit.get("status") != "PASS" or final_score.get("score") != 100, live_trade_blockers, "final_repo_audit_not_100")

    add_if(operator.get("safe_mode_active") is True or stability.get("safe_mode_active") is True, buy_order_alert_blockers, "safe_mode_active")
    add_if(operator.get("safe_mode_active") is True or stability.get("safe_mode_active") is True, paper_auto_trade_blockers, "safe_mode_active")
    add_if(operator.get("safe_mode_active") is True or stability.get("safe_mode_active") is True, auto_trade_blockers, "safe_mode_active")
    add_if(operator.get("safe_mode_active") is True or stability.get("safe_mode_active") is True, live_trade_blockers, "safe_mode_active")

    zero_price_rows = i(operator.get("zero_price_rows") or stability.get("zero_price_rows"))
    add_if(zero_price_rows > 0, buy_order_alert_blockers, "zero_price_rows_detected")
    add_if(zero_price_rows > 0, paper_auto_trade_blockers, "zero_price_rows_detected")
    add_if(zero_price_rows > 0, auto_trade_blockers, "zero_price_rows_detected")
    add_if(zero_price_rows > 0, live_trade_blockers, "zero_price_rows_detected")

    # Buy alert evidence.
    regime_pf = f(regime.get("profit_factor"))
    regime_avg = f(regime.get("avg_return_pct"))
    regime_tests = i(regime.get("total_tests"))

    add_if(regime.get("status") != "PASS", buy_order_alert_blockers, "price_regime_validation_not_pass")
    add_if(regime_pf < 1.2, buy_order_alert_blockers, "profit_factor_below_buy_alert_threshold_1_2")
    add_if(regime_avg <= 0, buy_order_alert_blockers, "avg_return_not_positive")
    add_if(regime_tests < 100, buy_order_alert_blockers, "sample_below_buy_alert_threshold_100")
    add_if(buy_alert.get("status") != "PASS", buy_order_alert_blockers, "buy_order_alert_mode_not_pass")
    add_if(buy_alert.get("order_submission") is not False, buy_order_alert_blockers, "buy_alert_order_submission_not_false")
    add_if(buy_alert.get("live_trading") is not False, buy_order_alert_blockers, "buy_alert_live_trading_not_false")

    # Feed/data quality checks.
    add_if(feed_status.get("status") == "FAIL", buy_order_alert_blockers, "feed_status_failed")
    add_if(feed_status.get("can_allow_buy_alerts_from_data") is not True, buy_order_alert_blockers, "feed_data_not_allowed_for_buy_alerts")
    add_if(feed_status.get("order_submission") is not False, buy_order_alert_blockers, "feed_status_order_submission_not_false")
    add_if(feed_status.get("live_trading") is not False, buy_order_alert_blockers, "feed_status_live_trading_not_false")

    buy_order_alert_ready = len(buy_order_alert_blockers) == 0

    # Validation core checks.
    add_if(validation_manifest.get("status") != "PASS", paper_auto_trade_blockers, "validation_core_manifest_not_pass")
    add_if(validation_status.get("validation_core_ready") is not True, paper_auto_trade_blockers, "validation_core_not_ready")
    add_if(slippage.get("slippage_model_ready") is not True, paper_auto_trade_blockers, "slippage_model_not_ready")
    add_if(forward.get("forward_validation_ready") is not True, paper_auto_trade_blockers, "forward_validation_not_ready")
    add_if(trade_journal.get("closed_trades", 0) is None, paper_auto_trade_blockers, "trade_journal_invalid")
    add_if(blocked_journal.get("status") not in {"PASS", "WARN"}, paper_auto_trade_blockers, "blocked_journal_not_pass_or_warn")

    # Paper auto-trade evidence thresholds.
    total_alerts = i(outcome.get("total_alerts"))
    closed_alerts = i(outcome.get("closed_alerts"))
    target_hits = i(outcome.get("target_hits"))
    stop_hits = i(outcome.get("stop_hits"))
    avg_alert_result = f(outcome.get("avg_result_return_pct"))
    closed_trades = i(trade_journal.get("closed_trades"))
    forward_ready = bool(forward.get("forward_validation_ready"))

    add_if(not buy_order_alert_ready, paper_auto_trade_blockers, "buy_order_alert_not_ready")
    add_if(total_alerts < 100, paper_auto_trade_blockers, "live_alert_outcome_sample_below_100")
    add_if(closed_alerts < 50, paper_auto_trade_blockers, "closed_alert_sample_below_50")
    add_if(closed_alerts > 0 and target_hits <= stop_hits, paper_auto_trade_blockers, "target_hits_not_above_stop_hits")
    add_if(closed_alerts > 0 and avg_alert_result <= 0, paper_auto_trade_blockers, "live_alert_avg_result_not_positive")
    add_if(closed_trades < 30, paper_auto_trade_blockers, "closed_trade_sample_below_30")
    add_if(regime_tests < 500, paper_auto_trade_blockers, "validated_setup_sample_below_500")
    add_if(regime_pf < 1.5, paper_auto_trade_blockers, "profit_factor_below_paper_auto_trade_threshold_1_5")
    add_if(not forward_ready, paper_auto_trade_blockers, "forward_validation_not_ready")

    # Required execution safety modules still missing.
    add_if(True, paper_auto_trade_blockers, "missing_duplicate_order_lock")
    add_if(True, paper_auto_trade_blockers, "missing_daily_loss_kill_switch")
    add_if(True, paper_auto_trade_blockers, "missing_bracket_order_lifecycle_test")
    add_if(True, paper_auto_trade_blockers, "missing_paper_execution_sandbox")

    # Propagate blockers upward.
    auto_trade_blockers.extend(paper_auto_trade_blockers)
    add_if(True, auto_trade_blockers, "paper_auto_trade_not_validated_for_multiple_weeks")

    live_trade_blockers.extend(auto_trade_blockers)
    add_if(True, live_trade_blockers, "live_trading_not_approved")
    add_if(True, live_trade_blockers, "manual_approval_required_before_any_live_order")

    # Hard final safety state.
    paper_auto_trade_ready = False
    auto_trade_ready = False
    live_trade_ready = False
    order_submission = False
    live_trading = False

    if buy_order_alert_ready:
        warnings.append("buy_order_alert_ready_but_auto_trade_blocked")

    status = "PASS" if buy_order_alert_ready else "WARN"

    health = {
        "schema_version": "auto_trade_readiness_health_v2",
        "generated_at": generated_at,
        "status": status,
        "buy_order_alert_ready": buy_order_alert_ready,
        "paper_auto_trade_ready": paper_auto_trade_ready,
        "auto_trade_ready": auto_trade_ready,
        "live_trade_ready": live_trade_ready,
        "order_submission": order_submission,
        "live_trading": live_trading,
        "warnings": warnings,
        "buy_order_alert_blockers": buy_order_alert_blockers,
        "paper_auto_trade_blockers": sorted(set(paper_auto_trade_blockers)),
        "auto_trade_blockers": sorted(set(auto_trade_blockers)),
        "live_trade_blockers": sorted(set(live_trade_blockers)),
        "evidence": {
            "final_repo_audit_status": final_audit.get("status"),
            "final_repo_audit_score": final_score.get("score"),
            "operator_health_status": operator.get("status"),
            "operator_stability_status": stability.get("status"),
            "price_regime_status": regime.get("status"),
            "price_regime_profit_factor": regime_pf,
            "price_regime_avg_return_pct": regime_avg,
            "price_regime_total_tests": regime_tests,
            "buy_order_alert_mode_status": buy_alert.get("status"),
            "buy_order_alert_eligible": buy_alert.get("buy_order_alert_eligible"),
            "feed_status": feed_status.get("status"),
            "feed_preferred_env": feed_status.get("preferred_feed_env"),
            "feed_rows_checked": feed_status.get("rows_checked"),
            "feed_rows_usable_for_buy_alert": feed_status.get("rows_usable_for_buy_alert"),
            "feed_rows_blocked_by_data_quality": feed_status.get("rows_blocked_by_data_quality"),
            "feed_can_allow_buy_alerts_from_data": feed_status.get("can_allow_buy_alerts_from_data"),
            "alert_total": total_alerts,
            "alert_closed": closed_alerts,
            "alert_target_hits": target_hits,
            "alert_stop_hits": stop_hits,
            "alert_avg_result_return_pct": avg_alert_result,
            "trade_journal_closed_trades": closed_trades,
            "blocked_journal_total_records": blocked_journal.get("total_records"),
            "slippage_model_ready": slippage.get("slippage_model_ready"),
            "forward_validation_ready": forward.get("forward_validation_ready"),
            "score_v2_status": score_v2.get("status"),
        },
        "decision": {
            "approved_now": "BUY_ORDER_ALERT_ONLY" if buy_order_alert_ready else "RESEARCH_ONLY",
            "not_approved": [
                "PAPER_AUTO_TRADE",
                "LIVE_TRADE",
                "AUTO_EXECUTION",
                "AUTO_CONFIG_OVERWRITE",
            ],
            "next_required_package": "Execution safety locks after live alert evidence grows",
        },
    }

    audit = {
        "schema_version": "auto_trade_readiness_audit_v2",
        "generated_at": generated_at,
        "health": health,
        "readiness_ladder": [
            {"level": 0, "name": "Research only", "ready": True},
            {"level": 1, "name": "Buy order alerts", "ready": buy_order_alert_ready},
            {"level": 2, "name": "Alert outcome journal", "ready": total_alerts >= 100 and closed_alerts >= 50},
            {"level": 3, "name": "Closed trade journal", "ready": closed_trades >= 30},
            {"level": 4, "name": "Forward validation", "ready": forward_ready},
            {"level": 5, "name": "Paper auto-trade review", "ready": paper_auto_trade_ready},
            {"level": 6, "name": "Live-readiness review", "ready": live_trade_ready},
        ],
        "hard_rules_before_paper_auto_trade": [
            "100+ live buy-order-alert outcomes tracked",
            "50+ closed alert outcomes",
            "target hits above stop hits",
            "positive live alert avg result",
            "30+ closed paper/simulated trades",
            "500+ validated setup tests",
            "profit_factor >= 1.5",
            "slippage model ready",
            "forward validation ready",
            "duplicate order lock present",
            "daily loss kill switch present",
            "bracket order lifecycle tested",
            "paper execution sandbox present",
        ],
        "safety": {
            "auto_config_overwrite": False,
            "order_submission": False,
            "live_trading": False,
        },
    }

    write_json(OUT_DOCS, audit)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, audit)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
