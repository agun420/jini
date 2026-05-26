"""
Package 111: Final Operator Decision Layer
==========================================
Purpose : Single source of truth for the operator view — sits downstream
          of every V3 scoring script and makes a final research mode decision.

Primary source  : EOD winner from v3_daily_research_report (NOT phase gate alone)
Current primary : PRE_BREAKOUT (validated by daily research report)
Phase gate role : Supporting input only
Dashboard role  : Additive panel — does NOT overwrite edgeRows / paperPlanRows
                  or replace any existing dashboard JSON

Safety (hardcoded — never overridden):
  order_submission        = False
  live_trading            = False
  paper_trade_ready       = False
  paper_order_submission  = False
  live_order_allowed      = False
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

# ---------------------------------------------------------------------------
# Input files — Package 111 reads only, never writes to these.
# ---------------------------------------------------------------------------
INPUTS = {
    "daily_report":       DOCS / "v3_daily_research_report.json",
    "outcome_quality":    DOCS / "v3_outcome_quality_audit.json",
    "prebreakout":        DOCS / "v3_prebreakout_predictor.json",
    "research_alert":     DOCS / "v3_research_alert_score.json",
    "paper_plan":         DOCS / "v3_paper_order_plan.json",
    "hard_safety_lock":   DOCS / "v3_hard_safety_lock.json",
    "package_100":        DOCS / "v3_package_100_validation.json",
    "loss_runner_gate":   DOCS / "v3_loss_learning_runner_gate.json",
    "phase_gate":         DOCS / "v3_phase_gate_verdict.json",
    "data_feed_quality":  DOCS / "data_feed_quality_health.json",
}

# ---------------------------------------------------------------------------
# Output files — additive only, new files Package 111 owns exclusively.
# ---------------------------------------------------------------------------
OUT_DOCS   = DOCS  / "v3_package_111_operator_decision.json"
OUT_HEALTH = DOCS  / "v3_package_111_operator_decision_health.json"
OUT_STATE  = STATE / "v3_package_111_operator_decision.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = {}
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


def _health(d: dict) -> dict:
    """Return the 'health' sub-dict if present, else the top-level dict."""
    return d.get("health") or d


def _str(v: Any) -> str:
    return str(v) if v is not None else "UNKNOWN"


# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------

FINAL_MODES = {
    "SAFETY_FAIL":             "Hard safety lock is not PASS. Research halted.",
    "PLAN_ONLY_DATA_WARNING":  "Data feed quality FAIL. Plan-only view with data caveat.",
    "PRE_BREAKOUT_PRIMARY":    "EOD validates Pre-Breakout as primary operator layer.",
    "REACTIVE_PRIMARY":        "EOD validates Reactive/Research-Alert as primary layer.",
    "RESEARCH_ONLY":           "No clear EOD winner yet. Research-only watch mode.",
}


def _determine_final_mode(
    safety_pass: bool,
    data_feed_fail: bool,
    eod_winning_layer: str | None,
) -> str:
    if not safety_pass:
        return "SAFETY_FAIL"
    if data_feed_fail:
        return "PLAN_ONLY_DATA_WARNING"
    layer = (eod_winning_layer or "").upper()
    if layer == "PRE_BREAKOUT":
        return "PRE_BREAKOUT_PRIMARY"
    if layer in ("REACTIVE", "RESEARCH_ALERT", "REACTIVE_ALERT"):
        return "REACTIVE_PRIMARY"
    return "RESEARCH_ONLY"


def _next_action(final_mode: str, plan_count: int, top_ticker: str | None) -> str:
    if final_mode == "SAFETY_FAIL":
        return (
            "Fix all hard_safety_lock blockers first. "
            "Run master-paid-alpaca-pipeline workflow to refresh health files."
        )
    if final_mode == "PLAN_ONLY_DATA_WARNING":
        return (
            "Data feed has zero-price rows. Review data_feed_quality_health.json. "
            "Plan-only mode active until feed quality recovers."
        )
    if final_mode == "PRE_BREAKOUT_PRIMARY":
        ticker_hint = f" Top candidate: {top_ticker}." if top_ticker else ""
        plan_hint   = f" {plan_count} plan entry/entries ready for review." if plan_count > 0 else ""
        return (
            f"Pre-Breakout is the primary research view.{ticker_hint}{plan_hint} "
            "No order submission. Review plan manually before any paper activation."
        )
    if final_mode == "REACTIVE_PRIMARY":
        return (
            "Reactive/Research-Alert is the primary research view. "
            "Pre-Breakout is secondary. No order submission."
        )
    return (
        "Watch mode. Continue collecting outcome data across both layers "
        "until one layer shows a clear statistical edge."
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    generated_at = now_iso()
    warnings: list[str] = []
    blockers: list[str] = []

    # --- Read all inputs -------------------------------------------------------
    daily_h        = _health(read_json(INPUTS["daily_report"]))
    outcome_h      = _health(read_json(INPUTS["outcome_quality"]))
    pre_h          = _health(read_json(INPUTS["prebreakout"]))
    reactive_d     = read_json(INPUTS["research_alert"])
    reactive_h     = _health(reactive_d)
    paper_plan_d   = read_json(INPUTS["paper_plan"])
    safety_lock_h  = _health(read_json(INPUTS["hard_safety_lock"]))
    pkg100_d       = read_json(INPUTS["package_100"])
    pkg100_h       = _health(pkg100_d)
    runner_h       = _health(read_json(INPUTS["loss_runner_gate"]))
    phase_h        = _health(read_json(INPUTS["phase_gate"]))
    feed_h         = read_json(INPUTS["data_feed_quality"])

    # --- Safety gate ----------------------------------------------------------
    safety_pass     = safety_lock_h.get("status") == "PASS" and \
                      safety_lock_h.get("safe_for_research") is True
    data_feed_fail  = _str(feed_h.get("status")) == "FAIL"

    if data_feed_fail:
        warnings.append("data_feed_quality_fail_plan_only_caveat")

    # --- EOD analysis ---------------------------------------------------------
    eod_winning_layer      = daily_h.get("winning_layer")          # e.g. "PRE_BREAKOUT"
    eod_promotion_decision = daily_h.get("promotion_decision")     # e.g. "PREBREAKOUT_LEADS_..."
    pre_avg_return         = daily_h.get("prebreakout_avg_return_pct")
    reactive_avg_return    = daily_h.get("reactive_avg_return_pct")
    avg_return_gap         = daily_h.get("avg_return_gap_pct")

    # Confirmed outcome stats from outcome_quality_audit (independent read).
    pre_target_hit_rate    = outcome_h.get("prebreakout_target_hit_rate_pct")
    pre_closed             = outcome_h.get("prebreakout_closed")
    reactive_target_hit    = outcome_h.get("reactive_target_hit_rate_pct")
    reactive_closed        = outcome_h.get("reactive_closed")

    # --- Prebreakout snapshot -------------------------------------------------
    pre_candidates         = pre_h.get("prebreakout_candidates", 0)
    pre_total_candidates   = pre_h.get("total_candidates", 0)
    pre_rows               = pre_h.get("rows", 0)
    pre_top_ticker         = pre_h.get("top_ticker")
    pre_top_score          = pre_h.get("top_score")
    pre_top_status         = pre_h.get("top_status")
    pre_market_regime      = pre_h.get("market_regime")
    pre_regime_score       = pre_h.get("market_regime_score")

    # --- Reactive snapshot ----------------------------------------------------
    reactive_candidates    = reactive_h.get("research_alert_candidates", 0) \
                             or reactive_h.get("candidates", 0)
    reactive_top_ticker    = reactive_h.get("top_ticker")

    # --- Paper plan -----------------------------------------------------------
    plan_count    = paper_plan_d.get("plan_count", 0)
    plan_rows_n   = len(paper_plan_d.get("plan_rows", []))

    # --- Runner gate ----------------------------------------------------------
    runner_watch  = runner_h.get("runner_watch_count", 0)
    runner_layer  = runner_h.get("winning_layer")

    # --- Package 100 ----------------------------------------------------------
    pkg100_score  = pkg100_h.get("score") or pkg100_d.get("health", {}).get("score")
    pkg100_status = _str(pkg100_h.get("status"))

    # --- Phase gate -----------------------------------------------------------
    phase_verdict_count = phase_h.get("verdict_count", 0)
    phase_top_ticker    = phase_h.get("top_ticker")
    phase_status        = _str(phase_h.get("status"))

    # --- Final mode decision --------------------------------------------------
    final_mode   = _determine_final_mode(safety_pass, data_feed_fail, eod_winning_layer)
    mode_message = FINAL_MODES.get(final_mode, "")

    primary_layer   = "PRE_BREAKOUT" if final_mode == "PRE_BREAKOUT_PRIMARY" \
                      else ("REACTIVE" if final_mode == "REACTIVE_PRIMARY" \
                      else "NONE")
    secondary_layer = "REACTIVE" if primary_layer == "PRE_BREAKOUT" \
                      else ("PRE_BREAKOUT" if primary_layer == "REACTIVE" else "NONE")

    next_action = _next_action(final_mode, plan_count, pre_top_ticker)

    # Validate: safety flags must never be True regardless of decision.
    if safety_lock_h.get("order_submission") is True:
        blockers.append("hard_safety_lock_order_submission_true")
    if safety_lock_h.get("live_trading") is True:
        blockers.append("hard_safety_lock_live_trading_true")

    grade = "PASS" if not blockers else "FAIL"

    # --- Build outputs --------------------------------------------------------
    health = {
        "schema_version": "v3_package_111_operator_decision_health_v1",
        "generated_at": generated_at,
        "status": grade,
        "blockers": blockers,
        "warnings": warnings,
        "final_mode": final_mode,
        "primary_operator_layer": primary_layer,
        "eod_winning_layer": eod_winning_layer,
        "safety_pass": safety_pass,
        "data_feed_fail": data_feed_fail,
        "pre_candidates": pre_candidates,
        "plan_count": plan_count,
        "phase_verdict_count": phase_verdict_count,
        "pkg100_score": pkg100_score,
        # Hard safety — always False.
        "order_submission": False,
        "live_trading": False,
        "paper_trade_ready": False,
        "paper_order_submission": False,
        "live_order_allowed": False,
    }

    out = {
        "schema_version": "v3_package_111_operator_decision_v1",
        "generated_at": generated_at,
        "health": health,

        # EOD validation context (direct read from daily research report).
        "eod_analysis": {
            "winning_layer": eod_winning_layer,
            "promotion_decision": eod_promotion_decision,
            "prebreakout_avg_return_pct": pre_avg_return,
            "reactive_avg_return_pct": reactive_avg_return,
            "avg_return_gap_pct": avg_return_gap,
            "prebreakout_closed": pre_closed,
            "prebreakout_target_hit_rate_pct": pre_target_hit_rate,
            "reactive_closed": reactive_closed,
            "reactive_target_hit_rate_pct": reactive_target_hit,
            "market_regime": pre_market_regime,
            "market_regime_score": pre_regime_score,
        },

        # Current intraday prebreakout snapshot.
        "prebreakout_snapshot": {
            "rows_enriched": pre_rows,
            "prebreakout_candidates": pre_candidates,
            "total_candidates": pre_total_candidates,
            "top_ticker": pre_top_ticker,
            "top_score": pre_top_score,
            "top_status": pre_top_status,
        },

        # Current reactive/research-alert snapshot.
        "reactive_snapshot": {
            "candidates": reactive_candidates,
            "top_ticker": reactive_top_ticker,
        },

        # Runner gate state.
        "runner_gate_snapshot": {
            "runner_watch_count": runner_watch,
            "winning_layer": runner_layer,
        },

        # Supporting inputs (phase gate is one of many, not the sole authority).
        "supporting_inputs": {
            "phase_gate_status": phase_status,
            "phase_gate_verdict_count": phase_verdict_count,
            "phase_gate_top_ticker": phase_top_ticker,
            "phase_gate_role": "supporting_input_only",
            "package_100_score": pkg100_score,
            "package_100_status": pkg100_status,
            "paper_plan_count": plan_count,
            "hard_safety_lock_status": _str(safety_lock_h.get("status")),
            "hard_safety_lock_safe_for_research": safety_lock_h.get("safe_for_research"),
            "data_feed_quality_status": _str(feed_h.get("status")),
        },

        # Operator decision.
        "operator_decision": {
            "final_mode": final_mode,
            "mode_message": mode_message,
            "primary_operator_layer": primary_layer,
            "secondary_operator_layer": secondary_layer,
            "eod_winner": eod_winning_layer,
            "eod_promotion_decision": eod_promotion_decision,
            "phase_gate_role": "supporting_input_only",
            "data_feed_warning": data_feed_fail,
            "safe_to_run_research": safety_pass,
            "next_action": next_action,
        },

        # Safety — hardcoded False, never overridden.
        "safety": {
            "research_only": True,
            "paper_plan_only": True,
            "order_submission": False,
            "live_trading": False,
            "paper_trade_ready": False,
            "paper_order_submission": False,
            "live_order_allowed": False,
            "not_financial_advice": True,
        },
    }

    write_json(OUT_DOCS, out)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, out)

    print(json.dumps(health, indent=2))

    if grade != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
