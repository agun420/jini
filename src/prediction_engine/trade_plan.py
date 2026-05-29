"""
Trade Plan Engine
=================
Turns a raw signal (price, levels, setup) into a complete, executable plan:

    Entry · Stop · Target1 (0.75R partial) · Target2 (open/resistance)
    R/R · Confidence · Signal STATE (when to enter) · Action (when to sell)

Signal lifecycle states (answers "when to enter"):
    POTENTIAL       — setup forming, price far below trigger (monitor only)
    WATCH           — approaching trigger (<1% away)
    TRIGGER_READY   — within 0.3% of trigger, prepare order
    ACTIVE          — triggered, price within 1R of entry → ENTER NOW
    EXTENDED        — price >1R past entry, missed it → don't chase
    AT_TARGET1      — T1 hit → trim half, trail stop to breakeven
    AT_TARGET2      — T2 hit → exit remainder
    STOPPED         — price at/below stop → exit
    STALE           — signal too old or structure broken

T1 = entry + 0.75R (tested scalp/partial). T2 = setup-specific (HOD break,
2R, or measured move).
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Tunables
T1_R_MULTIPLE       = 0.75   # T1 = entry + 0.75 * risk (partial / scalp)
DEFAULT_T2_R        = 2.0    # fallback T2 = entry + 2R if no structural target
TRIGGER_READY_PCT   = 0.30   # within 0.3% below entry → ready
WATCH_PCT           = 1.00   # within 1.0% below entry → watch
EXTENDED_R          = 1.00   # >1R past entry → extended (don't chase)
STALE_MINUTES       = 45     # signal older than this → stale


@dataclass
class TradePlan:
    entry:        float
    stop:         float
    target1:      float
    target2:      float
    risk_per_share: float
    rr:           float          # reward:risk to T2
    rr_t1:        float          # reward:risk to T1
    confidence:   float          # 0-100
    state:        str            # lifecycle state (see module docstring)
    action:       str            # plain-English what-to-do-now
    entry_zone:   str            # "ENTER NOW" / "WAIT" / "DONE"
    exit_guidance: str           # when/how to sell
    invalidation: str            # what kills the setup
    ready_since:  Optional[str] = None
    checked_at:   Optional[str] = None


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def _confidence(score: float, rr: float, rvol: float, danger: float) -> float:
    """Blend signal score, R/R quality, volume, and danger into 0-100 confidence."""
    score_c  = max(0.0, min(100.0, score))             # final_trade_score / explosion_prob
    rr_c     = max(0.0, min(100.0, (rr / 3.0) * 100))   # 3:1 RR = full marks
    vol_c    = max(0.0, min(100.0, (rvol - 1.0) * 50))  # 3x rvol = 100
    danger_c = max(0.0, 100.0 - danger)                 # low danger = high confidence
    conf = score_c * 0.45 + rr_c * 0.20 + vol_c * 0.15 + danger_c * 0.20
    return round(max(0.0, min(100.0, conf)), 1)


def build_trade_plan(
    *,
    price: float,
    entry: Optional[float] = None,
    stop: Optional[float] = None,
    target1: Optional[float] = None,
    target2: Optional[float] = None,
    vwap: Optional[float] = None,
    atr: Optional[float] = None,
    day_high: Optional[float] = None,
    setup_type: str = "NONE",
    score: float = 0.0,
    rvol: float = 1.0,
    danger: float = 0.0,
    ready_since: Optional[str] = None,
) -> TradePlan:
    """
    Build a complete trade plan. Missing levels are derived from price/vwap/atr.
    All prices in dollars. `score` is final_trade_score_v3 OR explosion_prob (0-100).
    """
    price = float(price or 0)

    # ── Derive entry if absent: break of recent high or current price ──────
    if not entry or entry <= 0:
        entry = round((day_high + 0.05) if day_high else price, 2)

    # ── Derive stop if absent: below VWAP or 1.5 ATR ──────────────────────
    if not stop or stop <= 0:
        if vwap and vwap > 0 and vwap < entry:
            stop = round(vwap - (atr * 0.5 if atr else entry * 0.004), 2)
        elif atr and atr > 0:
            stop = round(entry - atr * 1.5, 2)
        else:
            stop = round(entry * 0.994, 2)  # 0.6% default stop

    risk = max(0.01, entry - stop)

    # ── Targets ────────────────────────────────────────────────────────────
    if not target1 or target1 <= 0:
        target1 = round(entry + risk * T1_R_MULTIPLE, 2)   # 0.75R partial
    if not target2 or target2 <= 0:
        target2 = round(entry + risk * DEFAULT_T2_R, 2)    # 2R open

    rr     = round(_safe_div(target2 - entry, risk), 2)
    rr_t1  = round(_safe_div(target1 - entry, risk), 2)
    conf   = _confidence(score, rr, rvol, danger)

    # ── Lifecycle state machine ─────────────────────────────────────────────
    state, action, entry_zone, exit_guidance = _resolve_state(
        price, entry, stop, target1, target2, risk, ready_since
    )

    invalidation = _invalidation_text(setup_type, stop, vwap)

    return TradePlan(
        entry=round(entry, 2), stop=round(stop, 2),
        target1=round(target1, 2), target2=round(target2, 2),
        risk_per_share=round(risk, 2), rr=rr, rr_t1=rr_t1,
        confidence=conf, state=state, action=action,
        entry_zone=entry_zone, exit_guidance=exit_guidance,
        invalidation=invalidation,
        ready_since=ready_since,
        checked_at=datetime.now(ET).strftime("%H:%M ET"),
    )


def _resolve_state(price, entry, stop, t1, t2, risk, ready_since):
    """Return (state, action, entry_zone, exit_guidance) from price vs levels."""
    if price <= stop:
        return ("STOPPED", "EXIT — stop hit, setup invalidated", "DONE",
                "Exit immediately. Stop level breached.")

    if price >= t2:
        return ("AT_TARGET2", "SELL — T2 reached, close remaining position", "DONE",
                "Sell remainder at/above T2. Trade complete.")

    if price >= t1:
        return ("AT_TARGET1", "TRIM — T1 hit: sell 1/2, move stop to breakeven (entry)", "DONE",
                f"Take partial at T1 (${t1:.2f}). Trail stop to entry (${entry:.2f}); "
                f"let runner work toward T2 (${t2:.2f}).")

    if price >= entry:
        ext_r = _safe_div(price - entry, risk)
        if ext_r > EXTENDED_R:
            return ("EXTENDED", f"WAIT — extended {ext_r:.1f}R past entry, do not chase", "WAIT",
                    "Missed the clean entry. Wait for a pullback to entry/VWAP before considering.")
        return ("ACTIVE", "ENTER NOW — triggered and within 1R of entry", "ENTER NOW",
                f"In the entry zone. Stop ${stop:.2f}, first target ${t1:.2f}.")

    # Below entry → approaching
    dist_pct = _safe_div(entry - price, price) * 100
    stale = _is_stale(ready_since)
    if stale:
        return ("STALE", "SKIP — signal stale, re-validate before trading", "WAIT",
                "Setup has aged out. Wait for a fresh trigger.")
    if dist_pct <= TRIGGER_READY_PCT:
        return ("TRIGGER_READY", f"READY — {dist_pct:.2f}% below trigger, stage your order", "WAIT",
                f"Place buy-stop at ${entry:.2f}. Stop ${stop:.2f}, T1 ${t1:.2f}, T2 ${t2:.2f}.")
    if dist_pct <= WATCH_PCT:
        return ("WATCH", f"WATCH — {dist_pct:.2f}% below trigger, building", "WAIT",
                f"Not yet actionable. Trigger at ${entry:.2f}.")
    return ("POTENTIAL", f"MONITOR — {dist_pct:.2f}% below trigger, early", "WAIT",
            f"Setup forming. Needs to reach ${entry:.2f} to trigger.")


def _is_stale(ready_since: Optional[str]) -> bool:
    if not ready_since:
        return False
    try:
        dt = datetime.fromisoformat(ready_since)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ET)
        return (datetime.now(ET) - dt).total_seconds() / 60 > STALE_MINUTES
    except Exception:
        return False


def _invalidation_text(setup_type: str, stop: float, vwap: Optional[float]) -> str:
    base = f"Hard stop ${stop:.2f}. "
    if setup_type in ("VWAP_RECLAIM",):
        return base + "Invalidate on loss of VWAP/reclaim base, failed reclaim, or stale setup."
    if setup_type in ("COIL_BREAKOUT", "BULL_FLAG"):
        return base + "Invalidate on loss of the breakout base or volume failure on the break."
    if setup_type in ("GAP_GO", "ORB_LONG"):
        return base + "Invalidate on loss of opening range / VWAP or stalled momentum."
    if setup_type == "LATE_DAY_MOMO":
        return base + "Invalidate on loss of VWAP or reversal into the close."
    return base + "Invalidate on loss of trigger/base support or stale signal."


def plan_to_dict(plan: TradePlan) -> dict:
    return asdict(plan)
