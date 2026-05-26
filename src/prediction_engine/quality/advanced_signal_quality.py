from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


SIGNAL_CANDIDATES = [
    Path("docs/data/prediction_engine/signal_dashboard_news_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_finra_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard.json"),
]

MARKET_CANDIDATES = [
    Path("docs/data/prediction_engine/alpaca_paid_market_candidates.json"),
    Path("state/prediction_engine/dynamic_alpaca_candidates.json"),
]

ADAPTIVE_GUARD_PATH = Path("docs/data/prediction_engine/adaptive_guard.json")

OUTPUT_PATH = Path("docs/data/prediction_engine/signal_dashboard_quality_enriched.json")
QUALITY_DOCS_PATH = Path("docs/data/prediction_engine/advanced_signal_quality.json")
QUALITY_STATE_PATH = Path("state/prediction_engine/advanced_signal_quality.json")
QUALITY_HEALTH_PATH = Path("docs/data/prediction_engine/advanced_signal_quality_health.json")


THEMES = {
    "mega_cap_ai": {"NVDA", "MSFT", "GOOGL", "GOOG", "META", "AMZN", "AVGO", "AMD", "TSLA"},
    "small_cap_ai": {"SOUN", "BBAI", "AI", "PLTR", "SERV", "PATH"},
    "quantum": {"IONQ", "QBTS", "RGTI", "QUBT"},
    "crypto": {"COIN", "MARA", "RIOT", "CLSK", "WULF", "MSTR", "HOOD"},
    "ev": {"TSLA", "RIVN", "LCID", "NIO", "XPEV", "LI", "F", "GM"},
    "space_air": {"RKLB", "LUNR", "ASTS", "ACHR", "JOBY", "BA"},
    "meme_retail": {"GME", "AMC", "CVNA", "BYND", "FUBO"},
    "fintech": {"SOFI", "AFRM", "UPST", "HOOD", "COIN"},
    "travel_reopen": {"CCL", "NCLH", "DAL", "AAL", "UAL"},
}


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


def safe_symbol(row: Dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def extract_rows(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "signals", "candidates", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def load_best_signals() -> Tuple[Dict[str, Any], str]:
    for path in SIGNAL_CANDIDATES:
        payload = read_json(path, {})
        rows = extract_rows(payload)
        if rows:
            if not isinstance(payload, dict):
                payload = {"rows": rows}
            return payload, str(path)
    return {"rows": []}, "none"


def load_market_rows() -> Dict[str, Dict[str, Any]]:
    by_symbol: Dict[str, Dict[str, Any]] = {}
    for path in MARKET_CANDIDATES:
        payload = read_json(path, {})
        rows = extract_rows(payload)
        for row in rows:
            symbol = safe_symbol(row)
            if symbol:
                by_symbol[symbol] = row
    return by_symbol


def get_value(row: Dict[str, Any], market: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if row.get(key) is not None:
            return row.get(key)
        if market.get(key) is not None:
            return market.get(key)
    return None


def pct(value: Optional[float]) -> Optional[float]:
    return value if value is not None else None


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def spread_pct(row: Dict[str, Any], market: Dict[str, Any]) -> Optional[float]:
    bid = safe_float(get_value(row, market, "bid", "bid_price"))
    ask = safe_float(get_value(row, market, "ask", "ask_price"))
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        return None
    mid = (bid + ask) / 2
    if mid <= 0:
        return None
    return (ask - bid) / mid * 100.0


def dollar_volume(row: Dict[str, Any], market: Dict[str, Any]) -> Optional[float]:
    price = safe_float(get_value(row, market, "price", "close", "c"))
    volume = safe_float(get_value(row, market, "volume", "day_volume"))
    if price is None or volume is None:
        return None
    return price * volume


def score_spread(spread: Optional[float]) -> Tuple[float, List[str]]:
    reasons: List[str] = []
    if spread is None:
        return 8.0, ["spread_missing_neutral_score"]

    if spread <= 0.5:
        return 15.0, ["spread_tight"]
    if spread <= 1.0:
        return 12.0, ["spread_acceptable"]
    if spread <= 1.5:
        return 7.0, ["spread_caution"]
    return 0.0, ["spread_too_wide"]


def score_liquidity(dollar_vol: Optional[float]) -> Tuple[float, List[str]]:
    if dollar_vol is None:
        return 6.0, ["dollar_volume_missing_neutral_score"]
    if dollar_vol >= 20_000_000:
        return 15.0, ["strong_dollar_volume"]
    if dollar_vol >= 5_000_000:
        return 12.0, ["good_dollar_volume"]
    if dollar_vol >= 1_000_000:
        return 7.0, ["thin_but_tradeable_dollar_volume"]
    return 0.0, ["dollar_volume_too_low"]


def score_time_adjusted_rvol(row: Dict[str, Any], market: Dict[str, Any]) -> Tuple[float, List[str]]:
    rvol = safe_float(get_value(row, market, "relative_volume", "rvol"))
    if rvol is None:
        return 4.0, ["rvol_missing"]

    if rvol >= 8:
        return 14.0, ["extreme_rvol"]
    if rvol >= 5:
        return 16.0, ["very_strong_rvol"]
    if rvol >= 2:
        return 15.0, ["strong_rvol"]
    if rvol >= 1.5:
        return 9.0, ["moderate_rvol"]
    return 2.0, ["weak_rvol"]


def score_vwap_control(row: Dict[str, Any], market: Dict[str, Any]) -> Tuple[float, List[str]]:
    vwap_dist = safe_float(get_value(row, market, "vwap_distance_percent", "vwap_distance_pct"))
    if vwap_dist is None:
        return 4.0, ["vwap_distance_missing"]
    if 0 <= vwap_dist <= 4:
        return 18.0, ["vwap_controlled"]
    if 4 < vwap_dist <= 6:
        return 12.0, ["vwap_extended_caution"]
    if 6 < vwap_dist <= 8:
        return 4.0, ["vwap_chase_risk"]
    if vwap_dist < 0:
        return 0.0, ["below_vwap"]
    return 0.0, ["too_far_above_vwap"]


def anti_chase_score(row: Dict[str, Any], market: Dict[str, Any]) -> Tuple[float, List[str], List[str]]:
    reasons: List[str] = []
    blocks: List[str] = []

    day_change = safe_float(get_value(row, market, "day_move_percent", "day_change_pct", "day_change_percent"))
    vwap_dist = safe_float(get_value(row, market, "vwap_distance_percent", "vwap_distance_pct"))
    accel = safe_float(get_value(row, market, "volume_acceleration"))
    rvol = safe_float(get_value(row, market, "relative_volume", "rvol"))

    score = 15.0

    if day_change is not None:
        if day_change > 100:
            score -= 12
            blocks.append("day_move_parabolic_over_100")
        elif day_change > 60:
            score -= 8
            reasons.append("day_move_high_chase_risk")
        elif 3 <= day_change <= 25:
            score += 3
            reasons.append("day_move_controlled")

    if vwap_dist is not None:
        if vwap_dist > 10:
            score -= 12
            blocks.append("vwap_distance_over_10")
        elif vwap_dist > 8:
            score -= 8
            reasons.append("vwap_distance_high")
        elif 0 <= vwap_dist <= 4:
            score += 3
            reasons.append("not_chasing_vwap_controlled")

    if accel is not None and accel < 0.75:
        score -= 5
        reasons.append("volume_fading")

    if rvol is not None and rvol >= 10 and day_change is not None and day_change > 60:
        score -= 5
        reasons.append("extreme_rvol_with_parabolic_move")

    return clamp(score, 0, 20), reasons, blocks


def pullback_quality_score(row: Dict[str, Any], market: Dict[str, Any]) -> Tuple[float, List[str]]:
    vwap_dist = safe_float(get_value(row, market, "vwap_distance_percent", "vwap_distance_pct"))
    accel = safe_float(get_value(row, market, "volume_acceleration"))

    if vwap_dist is None:
        return 5.0, ["pullback_quality_unknown"]

    score = 0.0
    reasons = []

    if 0 <= vwap_dist <= 2:
        score += 15
        reasons.append("near_vwap_pullback_zone")
    elif 2 < vwap_dist <= 4:
        score += 12
        reasons.append("controlled_above_vwap")
    elif 4 < vwap_dist <= 6:
        score += 6
        reasons.append("extended_but_possible")
    elif vwap_dist < 0:
        score += 1
        reasons.append("below_vwap_no_pullback_entry")
    else:
        reasons.append("too_extended_for_pullback_entry")

    if accel is not None and accel >= 1.2 and score >= 6:
        score += 3
        reasons.append("volume_returning")

    return clamp(score, 0, 18), reasons


def breakout_compression_score(row: Dict[str, Any], market: Dict[str, Any]) -> Tuple[float, List[str]]:
    day_change = safe_float(get_value(row, market, "day_move_percent", "day_change_pct", "day_change_percent"))
    vwap_dist = safe_float(get_value(row, market, "vwap_distance_percent", "vwap_distance_pct"))
    accel = safe_float(get_value(row, market, "volume_acceleration"))
    rvol = safe_float(get_value(row, market, "relative_volume", "rvol"))

    score = 0.0
    reasons: List[str] = []

    if day_change is not None and 3 <= day_change <= 25:
        score += 6
        reasons.append("controlled_breakout_range")

    if vwap_dist is not None and 0 <= vwap_dist <= 4:
        score += 6
        reasons.append("breakout_not_overextended")

    if accel is not None and accel >= 1.25:
        score += 4
        reasons.append("breakout_volume_acceleration")

    if rvol is not None and rvol >= 2:
        score += 4
        reasons.append("breakout_confirmed_by_rvol")

    return clamp(score, 0, 20), reasons


def market_regime(signals: List[Dict[str, Any]], market_by_symbol: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    symbols = {"SPY", "QQQ", "IWM"}
    found: Dict[str, Dict[str, Any]] = {}

    for row in signals:
        sym = safe_symbol(row)
        if sym in symbols:
            found[sym] = row

    for sym in symbols:
        if sym not in found and sym in market_by_symbol:
            found[sym] = market_by_symbol[sym]

    bullish = 0
    bearish = 0
    details = {}

    for sym, row in found.items():
        vwap_dist = safe_float(row.get("vwap_distance_percent") or row.get("vwap_distance_pct"))
        day_change = safe_float(row.get("day_move_percent") or row.get("day_change_pct"))
        details[sym] = {
            "vwap_distance_pct": vwap_dist,
            "day_change_pct": day_change,
        }
        if vwap_dist is not None and vwap_dist > 0 and (day_change is None or day_change >= -0.5):
            bullish += 1
        elif vwap_dist is not None and vwap_dist < 0:
            bearish += 1

    if bullish >= 2:
        regime = "RISK_ON"
        score = 10
    elif bearish >= 2:
        regime = "RISK_OFF"
        score = -10
    else:
        regime = "NEUTRAL"
        score = 0

    return {
        "regime": regime,
        "market_regime_score": score,
        "details": details,
    }


def theme_for_symbol(symbol: str) -> Optional[str]:
    for theme, members in THEMES.items():
        if symbol in members:
            return theme
    return None


def theme_scores(signals: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    theme_stats: Dict[str, Dict[str, Any]] = {}
    for row in signals:
        sym = safe_symbol(row)
        theme = theme_for_symbol(sym)
        if not theme:
            continue
        stat = theme_stats.setdefault(theme, {"members": [], "avg_day_change": 0.0, "count": 0})
        day_change = safe_float(row.get("day_move_percent") or row.get("day_change_pct"), 0.0) or 0.0
        stat["members"].append(sym)
        stat["avg_day_change"] += day_change
        stat["count"] += 1

    for theme, stat in theme_stats.items():
        if stat["count"]:
            stat["avg_day_change"] = round(stat["avg_day_change"] / stat["count"], 4)
        stat["sympathy_score"] = 8 if stat["count"] >= 3 and stat["avg_day_change"] > 1 else 3 if stat["count"] >= 2 else 0

    return theme_stats


def halt_risk_score(row: Dict[str, Any], market: Dict[str, Any]) -> Tuple[float, List[str], List[str]]:
    reasons: List[str] = []
    blocks: List[str] = []

    day_change = safe_float(get_value(row, market, "day_move_percent", "day_change_pct", "day_change_percent"))
    vwap_dist = safe_float(get_value(row, market, "vwap_distance_percent", "vwap_distance_pct"))
    accel = safe_float(get_value(row, market, "volume_acceleration"))
    rvol = safe_float(get_value(row, market, "relative_volume", "rvol"))
    price = safe_float(get_value(row, market, "price"))

    risk = 0.0

    if day_change is not None and day_change > 80:
        risk += 35
        reasons.append("day_move_halt_risk")
    if vwap_dist is not None and vwap_dist > 10:
        risk += 20
        reasons.append("vwap_extension_halt_risk")
    if accel is not None and accel > 4:
        risk += 15
        reasons.append("volume_ignition_halt_risk")
    if rvol is not None and rvol > 12:
        risk += 15
        reasons.append("extreme_rvol_halt_risk")
    if price is not None and price < 3:
        risk += 15
        reasons.append("low_price_halt_risk")

    if risk >= 60:
        blocks.append("halt_risk_too_high")

    return clamp(risk, 0, 100), reasons, blocks


def quality_gate(row: Dict[str, Any], quality: Dict[str, Any]) -> Tuple[str, List[str]]:
    blocks: List[str] = []

    status = str(row.get("status") or row.get("signal") or "UNKNOWN")
    if status != "TRADE_ELIGIBLE":
        blocks.append(f"base_status_not_trade_eligible:{status}")

    spread = quality.get("spread_pct")
    if spread is not None and spread > 1.5:
        blocks.append("spread_above_1_5")

    dollar_vol = quality.get("dollar_volume")
    if dollar_vol is not None and dollar_vol < 1_000_000:
        blocks.append("dollar_volume_below_1m")

    if quality.get("halt_risk_score", 0) >= 60:
        blocks.append("halt_risk_high")

    if "vwap_distance_over_10" in quality.get("hard_blocks", []):
        blocks.append("anti_chase_vwap_extension")

    if "day_move_parabolic_over_100" in quality.get("hard_blocks", []):
        blocks.append("anti_chase_parabolic_move")

    if blocks:
        if any("base_status" in b for b in blocks):
            return "DASHBOARD_ONLY", blocks
        return "QUALITY_BLOCKED", blocks

    if quality.get("advanced_quality_score", 0) >= 75:
        return "QUALITY_APPROVED", []

    if quality.get("advanced_quality_score", 0) >= 60:
        return "QUALITY_CAUTION", ["quality_score_caution"]

    return "QUALITY_BLOCKED", ["quality_score_too_low"]


def enrich_row(row: Dict[str, Any], market_by_symbol: Dict[str, Any], themes: Dict[str, Dict[str, Any]], regime: Dict[str, Any]) -> Dict[str, Any]:
    sym = safe_symbol(row)
    market = market_by_symbol.get(sym, {})

    spread = spread_pct(row, market)
    dollar_vol = dollar_volume(row, market)

    spread_score, spread_reasons = score_spread(spread)
    liquidity_score, liquidity_reasons = score_liquidity(dollar_vol)
    rvol_score, rvol_reasons = score_time_adjusted_rvol(row, market)
    vwap_score, vwap_reasons = score_vwap_control(row, market)
    anti_score, anti_reasons, anti_blocks = anti_chase_score(row, market)
    pullback_score, pullback_reasons = pullback_quality_score(row, market)
    breakout_score, breakout_reasons = breakout_compression_score(row, market)
    halt_score, halt_reasons, halt_blocks = halt_risk_score(row, market)

    theme = theme_for_symbol(sym)
    sympathy_score = themes.get(theme, {}).get("sympathy_score", 0) if theme else 0

    raw_quality = (
        spread_score
        + liquidity_score
        + rvol_score
        + vwap_score
        + anti_score
        + pullback_score
        + breakout_score
        + sympathy_score
        + max(regime["market_regime_score"], -10)
        - (halt_score * 0.25)
    )

    quality = {
        "advanced_quality_score": round(clamp(raw_quality, 0, 100), 2),
        "spread_pct": round(spread, 4) if spread is not None else None,
        "dollar_volume": round(dollar_vol, 2) if dollar_vol is not None else None,
        "spread_score": round(spread_score, 2),
        "liquidity_score": round(liquidity_score, 2),
        "rvol_quality_score": round(rvol_score, 2),
        "vwap_control_score": round(vwap_score, 2),
        "anti_chase_score": round(anti_score, 2),
        "pullback_quality_score": round(pullback_score, 2),
        "breakout_compression_score": round(breakout_score, 2),
        "sympathy_score": round(sympathy_score, 2),
        "theme": theme,
        "halt_risk_score": round(halt_score, 2),
        "market_regime": regime["regime"],
        "reasons": (
            spread_reasons
            + liquidity_reasons
            + rvol_reasons
            + vwap_reasons
            + anti_reasons
            + pullback_reasons
            + breakout_reasons
            + halt_reasons
        )[:20],
        "hard_blocks": anti_blocks + halt_blocks,
    }

    gate_status, gate_blocks = quality_gate(row, quality)
    quality["quality_gate_status"] = gate_status
    quality["quality_gate_blocks"] = gate_blocks

    enriched = dict(row)
    enriched["advanced_quality"] = quality
    enriched["quality_gate_status"] = gate_status
    enriched["quality_gate_blocks"] = gate_blocks

    return enriched


def _construct_payloads(
    dashboard_payload: Dict[str, Any],
    signal_source: str,
    enriched_rows: List[Dict[str, Any]],
    market_by_symbol: Dict[str, Any],
    regime: Dict[str, Any],
    themes: Dict[str, Dict[str, Any]],
    approved_count: int,
    blocked_count: int,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    dashboard_payload["rows"] = enriched_rows
    dashboard_payload["schema_version"] = "signal_dashboard_quality_enriched_v1"
    dashboard_payload["quality_source"] = "advanced_signal_quality_v1"
    dashboard_payload["quality_generated_at"] = now_utc_iso()
    dashboard_payload["market_regime"] = regime
    dashboard_payload["theme_stats"] = themes

    quality_payload = {
        "schema_version": "advanced_signal_quality_v1",
        "generated_at": dashboard_payload["quality_generated_at"],
        "status": "PASS",
        "signal_source": signal_source,
        "market_rows_loaded": len(market_by_symbol),
        "counts": {
            "signals": len(enriched_rows),
            "quality_approved": approved_count,
            "quality_blocked": blocked_count,
            "dashboard_only_or_caution": len(enriched_rows) - approved_count - blocked_count,
        },
        "market_regime": regime,
        "theme_stats": themes,
        "rows": [
            {
                "ticker": row.get("ticker"),
                "status": row.get("status"),
                "quality_gate_status": row.get("quality_gate_status"),
                "advanced_quality": row.get("advanced_quality"),
            }
            for row in enriched_rows
        ],
        "safety": {
            "paper_only": True,
            "order_submission": False,
            "quality_gate_cannot_submit_orders": True,
            "disclaimer": "Quality scoring only. Not financial advice.",
        },
    }

    return dashboard_payload, quality_payload


def build_quality_payload() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    dashboard_payload, signal_source = load_best_signals()
    rows = extract_rows(dashboard_payload)
    market_by_symbol = load_market_rows()
    regime = market_regime(rows, market_by_symbol)
    themes = theme_scores(rows)

    enriched_rows: List[Dict[str, Any]] = []
    approved_count = 0
    blocked_count = 0

    for row in rows:
        enriched = enrich_row(row, market_by_symbol, themes, regime)
        enriched_rows.append(enriched)

        if enriched["quality_gate_status"] == "QUALITY_APPROVED":
            approved_count += 1
        elif enriched["quality_gate_status"] == "QUALITY_BLOCKED":
            blocked_count += 1

    enriched_rows.sort(
        key=lambda item: (
            1 if item.get("quality_gate_status") == "QUALITY_APPROVED" else 0,
            float((item.get("advanced_quality") or {}).get("advanced_quality_score") or 0),
            float(item.get("score") or 0),
        ),
        reverse=True,
    )

    return _construct_payloads(
        dashboard_payload,
        signal_source,
        enriched_rows,
        market_by_symbol,
        regime,
        themes,
        approved_count,
        blocked_count,
    )


def export_quality() -> Dict[str, Any]:
    dashboard_payload, quality_payload = build_quality_payload()

    health = {
        "schema_version": "advanced_signal_quality_health_v1",
        "generated_at": quality_payload["generated_at"],
        "status": quality_payload["status"],
        "signals": quality_payload["counts"]["signals"],
        "quality_approved": quality_payload["counts"]["quality_approved"],
        "quality_blocked": quality_payload["counts"]["quality_blocked"],
        "market_regime": quality_payload["market_regime"]["regime"],
        "paper_only": True,
        "order_submission": False,
    }

    write_json(OUTPUT_PATH, dashboard_payload)
    write_json(QUALITY_DOCS_PATH, quality_payload)
    write_json(QUALITY_STATE_PATH, quality_payload)
    write_json(QUALITY_HEALTH_PATH, health)

    return {
        "status": "PASS",
        "signals": quality_payload["counts"]["signals"],
        "quality_approved": quality_payload["counts"]["quality_approved"],
        "market_regime": quality_payload["market_regime"]["regime"],
        "output_path": str(OUTPUT_PATH),
        "quality_path": str(QUALITY_DOCS_PATH),
        "health_path": str(QUALITY_HEALTH_PATH),
    }


def main() -> None:
    print(json.dumps(export_quality(), indent=2))


if __name__ == "__main__":
    main()
