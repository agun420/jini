from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

PRE_JOURNAL = DOCS / "v3_prebreakout_outcome_journal.json"
REACTIVE_JOURNAL = DOCS / "v3_research_alert_outcome_journal.json"
PHASE_VERDICT = DOCS / "v3_phase_gate_verdict.json"
PHASE_HEALTH = DOCS / "v3_phase_gate_verdict_health.json"
EDGE = DOCS / "v3_mathematical_edge_model.json"
PAPER_PLAN = DOCS / "v3_paper_order_plan.json"
SAFETY = DOCS / "v3_hard_safety_lock_health.json"
REGIME = DOCS / "v3_market_regime_filter_health.json"
DAILY = DOCS / "v3_daily_research_report_health.json"

OUT_DOCS = DOCS / "v3_loss_learning_runner_gate.json"
OUT_HEALTH = DOCS / "v3_loss_learning_runner_gate_health.json"
OUT_STATE = STATE / "v3_loss_learning_runner_gate.json"


TARGET_COOLDOWN_MINUTES = 45
STOP_LOCKOUT_MINUTES = 390
MAX_FAILED_ALERTS_PER_DAY = 2
LATE_DAY_HOUR = 14
LATE_DAY_MINUTE = 45
VERY_LATE_HOUR = 15
VERY_LATE_MINUTE = 30


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def now_et() -> datetime:
    return datetime.now(ZoneInfo("America/New_York"))


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        s = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


def minutes_since(dt: datetime | None) -> float | None:
    if not dt:
        return None
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 60.0)


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


def f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def ticker(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    return [r for r in value if isinstance(r, dict)] if isinstance(value, list) else []


def all_closed_alerts(pre: dict[str, Any], reactive: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for layer, payload in [("PRE_BREAKOUT", pre), ("REACTIVE", reactive)]:
        for r in rows(payload, "closed_alerts"):
            rr = dict(r)
            rr["learning_layer"] = layer
            out.append(rr)
    out.sort(key=lambda r: str(r.get("closed_at") or ""), reverse=True)
    return out


def build_ticker_memory(alerts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mem: dict[str, dict[str, Any]] = {}

    for r in alerts:
        sym = ticker(r)
        if not sym:
            continue

        m = mem.setdefault(sym, {
            "ticker": sym,
            "closed_count": 0,
            "target_hits": 0,
            "stop_hits": 0,
            "time_exits": 0,
            "failed_alerts": 0,
            "avg_return_pct": 0.0,
            "total_return_pct": 0.0,
            "last_reason": None,
            "last_closed_at": None,
            "last_return_pct": None,
            "last_layer": None,
            "last_score": None,
        })

        ret = f(r.get("return_pct"))
        reason = str(r.get("exit_reason") or "").upper()
        closed_at = r.get("closed_at")

        m["closed_count"] += 1
        m["total_return_pct"] += ret
        m["avg_return_pct"] = m["total_return_pct"] / max(1, m["closed_count"])

        if reason == "TARGET_HIT":
            m["target_hits"] += 1
        elif reason == "STOP_HIT":
            m["stop_hits"] += 1
            m["failed_alerts"] += 1
        elif reason == "TIME_EXIT":
            m["time_exits"] += 1
            if ret <= 0:
                m["failed_alerts"] += 1

        # alerts are sorted newest first, so keep first as latest
        if m["last_closed_at"] is None:
            m["last_reason"] = reason
            m["last_closed_at"] = closed_at
            m["last_return_pct"] = ret
            m["last_layer"] = r.get("learning_layer")
            m["last_score"] = r.get("prebreakout_score_v3") or r.get("research_alert_score_v3")

    return mem


def cooldown_for(sym: str, memory: dict[str, Any], current_et: datetime) -> dict[str, Any]:
    reason = str(memory.get("last_reason") or "").upper()
    last_closed = parse_dt(memory.get("last_closed_at"))
    mins = minutes_since(last_closed)
    failed = int(memory.get("failed_alerts") or 0)

    cooldown_active = False
    cooldown_reason = None
    cooldown_minutes_left = 0.0

    if failed >= MAX_FAILED_ALERTS_PER_DAY:
        cooldown_active = True
        cooldown_reason = "two_failed_alerts_today"
        cooldown_minutes_left = 999.0

    elif reason == "STOP_HIT":
        cooldown_active = True
        cooldown_reason = "post_stop_lockout"
        cooldown_minutes_left = max(0.0, STOP_LOCKOUT_MINUTES - (mins or 0.0))

    elif reason == "TARGET_HIT" and mins is not None and mins < TARGET_COOLDOWN_MINUTES:
        cooldown_active = True
        cooldown_reason = "post_target_cooldown"
        cooldown_minutes_left = max(0.0, TARGET_COOLDOWN_MINUTES - mins)

    elif reason == "TIME_EXIT" and f(memory.get("last_return_pct")) <= 0 and mins is not None and mins < TARGET_COOLDOWN_MINUTES:
        cooldown_active = True
        cooldown_reason = "weak_time_exit_cooldown"
        cooldown_minutes_left = max(0.0, TARGET_COOLDOWN_MINUTES - mins)

    # Late day global risk.
    late_day = (
        current_et.hour > LATE_DAY_HOUR
        or (current_et.hour == LATE_DAY_HOUR and current_et.minute >= LATE_DAY_MINUTE)
    )
    very_late = (
        current_et.hour > VERY_LATE_HOUR
        or (current_et.hour == VERY_LATE_HOUR and current_et.minute >= VERY_LATE_MINUTE)
    )

    return {
        "ticker": sym,
        "cooldown_active": cooldown_active,
        "cooldown_reason": cooldown_reason,
        "cooldown_minutes_left": round(cooldown_minutes_left, 2),
        "late_day": late_day,
        "very_late_day": very_late,
        "last_reason": memory.get("last_reason"),
        "last_closed_at": memory.get("last_closed_at"),
        "last_return_pct": memory.get("last_return_pct"),
        "closed_count": memory.get("closed_count"),
        "target_hits": memory.get("target_hits"),
        "stop_hits": memory.get("stop_hits"),
        "time_exits": memory.get("time_exits"),
        "failed_alerts": memory.get("failed_alerts"),
        "avg_return_pct": round(f(memory.get("avg_return_pct")), 4),
    }


def verdict_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {ticker(r): r for r in rows(payload, "verdicts") if ticker(r)}


def edge_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {ticker(r): r for r in rows(payload, "candidates") if ticker(r)}


def plan_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {ticker(r): r for r in rows(payload, "plans") if ticker(r)}


def runner_gate(
    sym: str,
    verdict: dict[str, Any],
    edge: dict[str, Any],
    plan: dict[str, Any],
    cool: dict[str, Any],
    regime: str,
    safety_ok: bool,
) -> dict[str, Any]:
    gates = verdict.get("phase_gates") if isinstance(verdict.get("phase_gates"), dict) else {}
    pre_gate = gates.get("pre_breakout", {}) if isinstance(gates.get("pre_breakout"), dict) else {}
    math_gate = gates.get("math_edge", {}) if isinstance(gates.get("math_edge"), dict) else {}

    final_verdict = str(verdict.get("final_verdict") or "").upper()
    pre_status = str(pre_gate.get("status") or "").upper()
    math_status = str(math_gate.get("status") or "").upper()

    ev = f(verdict.get("expected_value_pct") or edge.get("expected_value_pct"))
    edge_score = f(verdict.get("edge_score") or edge.get("edge_score"))
    day_move = f(verdict.get("day_move_pct") or edge.get("day_move_pct"))
    rvol = f(verdict.get("relative_volume") or edge.get("relative_volume"))
    price = f(verdict.get("price") or edge.get("live_price") or plan.get("live_price") or plan.get("price"))
    target = f(verdict.get("target_price") or edge.get("target_price") or plan.get("target_price"))
    stop = f(verdict.get("stop_price") or edge.get("stop_price") or plan.get("stop_price"))

    blockers: list[str] = []
    warnings: list[str] = []

    if not safety_ok:
        blockers.append("safety_not_pass")
    if regime == "RISK_OFF":
        blockers.append("risk_off_market")
    if cool.get("cooldown_active"):
        blockers.append(str(cool.get("cooldown_reason") or "cooldown_active"))
    if cool.get("very_late_day"):
        blockers.append("very_late_day_no_new_runner")
    elif cool.get("late_day"):
        warnings.append("late_day_requires_elite_setup")
    if pre_status not in {"PASS", "WATCH"} and "BUY SETUP" not in final_verdict:
        blockers.append("prebreakout_not_ready")
    if math_status != "PASS" and ev <= 0:
        blockers.append("math_edge_not_positive")
    if ev < 0.15:
        blockers.append("expected_value_too_low")
    if edge_score < 70:
        warnings.append("edge_score_below_elite")
    if rvol < 1.0:
        warnings.append("rvol_below_runner_preference")
    if day_move > 12:
        warnings.append("day_move_may_be_extended")
    if price <= 0:
        blockers.append("missing_price")
    if target <= price:
        warnings.append("base_target_not_above_price")

    runner_watch = not blockers and (
        ev >= 0.15
        and edge_score >= 70
        and rvol >= 1.0
        and day_move <= 12
    )

    # Runner plan is review-only. No orders.
    first_target_pct = 0.8
    runner_target_pct = 5.0 if day_move < 6 else 3.0
    max_runner_target_pct = 10.0
    breakeven_after_first_target = True

    return {
        "ticker": sym,
        "runner_watch": runner_watch,
        "runner_status": "RUNNER WATCH - PLAN ONLY" if runner_watch else "NO RUNNER",
        "blockers": blockers,
        "warnings": warnings,
        "price": price,
        "day_move_pct": day_move,
        "relative_volume": rvol,
        "expected_value_pct": ev,
        "edge_score": edge_score,
        "base_target_price": target if target > 0 else None,
        "base_stop_price": stop if stop > 0 else None,
        "runner_first_target_pct": first_target_pct,
        "runner_target_pct": runner_target_pct,
        "runner_max_target_pct": max_runner_target_pct,
        "breakeven_after_first_target": breakeven_after_first_target,
        "order_submission": False,
        "live_trading": False,
    }


def main() -> None:
    generated_at = now_iso()
    current_et = now_et()

    pre = read_json(PRE_JOURNAL, {})
    reactive = read_json(REACTIVE_JOURNAL, {})
    phase = read_json(PHASE_VERDICT, {})
    phase_h = read_json(PHASE_HEALTH, {})
    edge = read_json(EDGE, {})
    paper = read_json(PAPER_PLAN, {})
    safety = read_json(SAFETY, {})
    regime_h = read_json(REGIME, {})
    daily = read_json(DAILY, {})

    alerts = all_closed_alerts(pre, reactive)
    memory = build_ticker_memory(alerts)

    vmap = verdict_map(phase)
    emap = edge_map(edge)
    pmap = plan_map(paper)

    symbols: list[str] = []
    for source in (vmap, emap, pmap, memory):
        for sym in source.keys():
            if sym and sym not in symbols:
                symbols.append(sym)

    regime = str(regime_h.get("regime") or "UNKNOWN").upper()
    safety_ok = (
        safety.get("status") == "PASS"
        and safety.get("safe_for_research") is True
        and safety.get("order_submission") is False
        and safety.get("live_trading") is False
    )

    cooldowns = []
    runner_rows = []
    blocked_rows = []

    for sym in symbols:
        mem = memory.get(sym, {"ticker": sym})
        cool = cooldown_for(sym, mem, current_et)
        cooldowns.append(cool)

        runner = runner_gate(
            sym,
            vmap.get(sym, {"ticker": sym}),
            emap.get(sym, {"ticker": sym}),
            pmap.get(sym, {"ticker": sym}),
            cool,
            regime,
            safety_ok,
        )
        runner_rows.append(runner)
        if runner["blockers"]:
            blocked_rows.append(runner)

    runner_rows.sort(
        key=lambda r: (
            1 if r.get("runner_watch") else 0,
            f(r.get("expected_value_pct")),
            f(r.get("edge_score")),
            f(r.get("relative_volume")),
        ),
        reverse=True,
    )

    cooldown_active = [c for c in cooldowns if c.get("cooldown_active")]
    runner_watch = [r for r in runner_rows if r.get("runner_watch")]

    blockers: list[str] = []
    warnings: list[str] = []

    if not safety_ok:
        warnings.append("safety_not_pass_runner_gate_review_only")
    if not runner_watch:
        warnings.append("no_runner_watch_candidates")

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "v3_loss_learning_runner_gate_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "market_regime": regime,
        "winning_layer": daily.get("winning_layer"),
        "promotion_decision": daily.get("promotion_decision"),
        "ticker_memory_count": len(memory),
        "cooldown_active_count": len(cooldown_active),
        "runner_watch_count": len(runner_watch),
        "blocked_runner_count": len(blocked_rows),
        "top_runner_ticker": runner_watch[0]["ticker"] if runner_watch else None,
        "top_runner_ev_pct": runner_watch[0]["expected_value_pct"] if runner_watch else None,
        "late_day": current_et.hour > LATE_DAY_HOUR or (current_et.hour == LATE_DAY_HOUR and current_et.minute >= LATE_DAY_MINUTE),
        "very_late_day": current_et.hour > VERY_LATE_HOUR or (current_et.hour == VERY_LATE_HOUR and current_et.minute >= VERY_LATE_MINUTE),
        "paper_trade_ready": False,
        "paper_order_allowed": False,
        "order_submission": False,
        "live_trading": False,
    }

    out = {
        "schema_version": "v3_loss_learning_runner_gate_v1",
        "generated_at": generated_at,
        "health": health,
        "ticker_memory": memory,
        "cooldowns": cooldowns,
        "active_cooldowns": cooldown_active,
        "runner_candidates": runner_rows,
        "runner_watch": runner_watch,
        "blocked_runner_candidates": blocked_rows[:50],
        "rules": {
            "target_cooldown_minutes": TARGET_COOLDOWN_MINUTES,
            "stop_lockout_minutes": STOP_LOCKOUT_MINUTES,
            "max_failed_alerts_per_day": MAX_FAILED_ALERTS_PER_DAY,
            "late_day_after_et": f"{LATE_DAY_HOUR:02d}:{LATE_DAY_MINUTE:02d}",
            "very_late_after_et": f"{VERY_LATE_HOUR:02d}:{VERY_LATE_MINUTE:02d}",
            "runner_first_target_pct": 0.8,
            "runner_target_pct_range": "3%-10% depending on setup quality and extension",
        },
        "safety": {
            "loss_learning_only": True,
            "runner_gate_only": True,
            "paper_plan_only": True,
            "order_submission": False,
            "live_trading": False,
        },
    }

    write_json(OUT_DOCS, out)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, out)

    print(json.dumps(health, indent=2))

    if status == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
