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
PAPER_ALERT_HEALTH = DOCS / "paper_alert_watch_mode_health.json"

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


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    generated_at = now()

    operator = read_json(OPERATOR_HEALTH, {})
    stability = read_json(STABILITY_HEALTH, {})
    final_audit = read_json(FINAL_AUDIT, {})
    final_score = final_audit.get("score", {}) if isinstance(final_audit, dict) else {}
    regime = read_json(PRICE_REGIME_HEALTH, {})
    score_v2 = read_json(SCORE_V2_HEALTH, {})

    # Support either new buy-order-alert naming or old watch-mode naming.
    buy_alert = read_json(BUY_ALERT_HEALTH, {})
    if not buy_alert:
        buy_alert = read_json(PAPER_ALERT_HEALTH, {})

    blockers_auto_trade: list[str] = []
    blockers_paper_auto_trade: list[str] = []
    blockers_buy_order_alert: list[str] = []
    blockers_live_trade: list[str] = []
    warnings: list[str] = []

    # Core infrastructure checks.
    if operator.get("status") not in {"PASS", "WARN"}:
        blockers_buy_order_alert.append("operator_health_not_pass_or_warn")
        blockers_paper_auto_trade.append("operator_health_not_pass_or_warn")
        blockers_auto_trade.append("operator_health_not_pass_or_warn")
        blockers_live_trade.append("operator_health_not_pass_or_warn")

    if stability.get("blockers"):
        blockers_buy_order_alert.append("operator_stability_has_blockers")
        blockers_paper_auto_trade.append("operator_stability_has_blockers")
        blockers_auto_trade.append("operator_stability_has_blockers")
        blockers_live_trade.append("operator_stability_has_blockers")

    if final_audit.get("status") != "PASS" or final_score.get("score") != 100:
        blockers_buy_order_alert.append("final_repo_audit_not_100")
        blockers_paper_auto_trade.append("final_repo_audit_not_100")
        blockers_auto_trade.append("final_repo_audit_not_100")
        blockers_live_trade.append("final_repo_audit_not_100")

    if operator.get("safe_mode_active") is True or stability.get("safe_mode_active") is True:
        blockers_buy_order_alert.append("safe_mode_active")
        blockers_paper_auto_trade.append("safe_mode_active")
        blockers_auto_trade.append("safe_mode_active")
        blockers_live_trade.append("safe_mode_active")

    if int(operator.get("zero_price_rows") or stability.get("zero_price_rows") or 0) > 0:
        blockers_buy_order_alert.append("zero_price_rows_detected")
        blockers_paper_auto_trade.append("zero_price_rows_detected")
        blockers_auto_trade.append("zero_price_rows_detected")
        blockers_live_trade.append("zero_price_rows_detected")

    # Research evidence checks.
    regime_pf = f(regime.get("profit_factor"))
    regime_avg = f(regime.get("avg_return_pct"))
    regime_tests = int(f(regime.get("total_tests")))

    if regime.get("status") != "PASS":
        blockers_buy_order_alert.append("price_regime_validation_not_pass")
        blockers_paper_auto_trade.append("price_regime_validation_not_pass")
        blockers_auto_trade.append("price_regime_validation_not_pass")
        blockers_live_trade.append("price_regime_validation_not_pass")

    if regime_pf < 1.2:
        blockers_buy_order_alert.append("profit_factor_below_buy_alert_threshold")
    if regime_avg <= 0:
        blockers_buy_order_alert.append("avg_return_not_positive")
    if regime_tests < 100:
        blockers_buy_order_alert.append("sample_below_buy_alert_threshold")

    # Auto-trading requires much more proof than alerts.
    if regime_pf < 1.5:
        blockers_paper_auto_trade.append("profit_factor_below_paper_auto_trade_threshold_1_5")
        blockers_auto_trade.append("profit_factor_below_auto_trade_threshold_1_5")
        blockers_live_trade.append("profit_factor_below_live_trade_threshold_1_5")

    if regime_tests < 500:
        blockers_paper_auto_trade.append("sample_below_paper_auto_trade_threshold_500")
        blockers_auto_trade.append("sample_below_auto_trade_threshold_500")
        blockers_live_trade.append("sample_below_live_trade_threshold_500")

    if regime_avg <= 0:
        blockers_paper_auto_trade.append("avg_return_not_positive")
        blockers_auto_trade.append("avg_return_not_positive")
        blockers_live_trade.append("avg_return_not_positive")

    # Required future evidence layers.
    blockers_paper_auto_trade.append("missing_live_alert_outcome_journal_100_plus_alerts")
    blockers_paper_auto_trade.append("missing_slippage_and_spread_execution_model")
    blockers_paper_auto_trade.append("missing_duplicate_order_lock")
    blockers_paper_auto_trade.append("missing_daily_loss_kill_switch")
    blockers_paper_auto_trade.append("missing_bracket_order_lifecycle_test")

    blockers_auto_trade.extend(blockers_paper_auto_trade)
    blockers_auto_trade.append("paper_auto_trade_not_validated_for_multiple_weeks")

    blockers_live_trade.extend(blockers_auto_trade)
    blockers_live_trade.append("live_trading_not_approved")
    blockers_live_trade.append("manual_approval_required_before_any_live_order")

    # Hard safety truth.
    order_submission = False
    live_trading = False

    buy_order_alert_ready = not blockers_buy_order_alert
    paper_auto_trade_ready = False
    auto_trade_ready = False
    live_trade_ready = False

    if buy_order_alert_ready and not paper_auto_trade_ready:
        warnings.append("buy_order_alert_ready_but_auto_trade_blocked")

    status = "PASS" if buy_order_alert_ready else "WARN"

    health = {
        "schema_version": "auto_trade_readiness_health_v1",
        "generated_at": generated_at,
        "status": status,
        "buy_order_alert_ready": buy_order_alert_ready,
        "paper_auto_trade_ready": paper_auto_trade_ready,
        "auto_trade_ready": auto_trade_ready,
        "live_trade_ready": live_trade_ready,
        "order_submission": order_submission,
        "live_trading": live_trading,
        "warnings": warnings,
        "buy_order_alert_blockers": blockers_buy_order_alert,
        "paper_auto_trade_blockers": blockers_paper_auto_trade,
        "auto_trade_blockers": blockers_auto_trade,
        "live_trade_blockers": blockers_live_trade,
        "evidence": {
            "final_repo_audit_status": final_audit.get("status"),
            "final_repo_audit_score": final_score.get("score"),
            "operator_health_status": operator.get("status"),
            "operator_stability_status": stability.get("status"),
            "price_regime_status": regime.get("status"),
            "price_regime_profit_factor": regime_pf,
            "price_regime_avg_return_pct": regime_avg,
            "price_regime_total_tests": regime_tests,
            "score_v2_status": score_v2.get("status"),
        },
        "decision": {
            "approved_now": "BUY_ORDER_ALERT_ONLY",
            "not_approved": [
                "PAPER_AUTO_TRADE",
                "LIVE_TRADE",
                "AUTO_EXECUTION",
            ],
            "next_required_package": "Buy Order Alert Gate + Alert Outcome Journal",
        },
    }

    audit = {
        "schema_version": "auto_trade_readiness_audit_v1",
        "generated_at": generated_at,
        "health": health,
        "readiness_ladder": [
            {
                "level": 0,
                "name": "Research only",
                "status": "COMPLETE",
            },
            {
                "level": 1,
                "name": "Buy order alerts only",
                "status": "READY" if buy_order_alert_ready else "BLOCKED",
            },
            {
                "level": 2,
                "name": "Alert outcome journal",
                "status": "NEXT",
            },
            {
                "level": 3,
                "name": "Paper auto-trade sandbox",
                "status": "BLOCKED",
            },
            {
                "level": 4,
                "name": "Paper auto-trade with bracket orders",
                "status": "BLOCKED",
            },
            {
                "level": 5,
                "name": "Live-readiness review",
                "status": "BLOCKED",
            },
            {
                "level": 6,
                "name": "Live trading",
                "status": "BLOCKED",
            },
        ],
        "hard_rules_before_paper_auto_trade": [
            "500+ validated setup tests",
            "profit_factor >= 1.5",
            "avg_return_pct > 0",
            "100+ live buy-order-alert outcomes tracked",
            "spread/slippage model present",
            "duplicate order lock present",
            "daily loss kill switch present",
            "paper bracket order lifecycle tested",
            "order_submission remains false until explicit paper sandbox package",
        ],
        "hard_rules_before_live_trade": [
            "several weeks of profitable paper automation",
            "manual live-readiness approval",
            "live_trading remains false until separate explicit approval",
            "max notional and daily loss limits enforced",
            "broker-side risk controls verified",
        ],
    }

    write_json(OUT_DOCS, audit)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, audit)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
