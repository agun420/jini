from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


SIGNAL_CANDIDATES = [
    Path("docs/data/prediction_engine/signal_dashboard_quality_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_news_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_finra_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard.json"),
]
MARKET_CANDIDATES = [
    Path("docs/data/prediction_engine/alpaca_paid_market_candidates.json"),
    Path("state/prediction_engine/dynamic_alpaca_candidates.json"),
]

OUTPUT_DASHBOARD_PATH = Path("docs/data/prediction_engine/signal_dashboard_market_guard_enriched.json")
OUTPUT_DOCS_PATH = Path("docs/data/prediction_engine/halt_luld_circuit_guard.json")
OUTPUT_STATE_PATH = Path("state/prediction_engine/halt_luld_circuit_guard.json")
HEALTH_PATH = Path("docs/data/prediction_engine/halt_luld_circuit_guard_health.json")


INDEX_SYMBOLS = {"SPY", "QQQ", "IWM"}


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


def load_dashboard() -> tuple[Dict[str, Any], str]:
    for path in SIGNAL_CANDIDATES:
        payload = read_json(path, {})
        rows = extract_rows(payload)
        if rows:
            if not isinstance(payload, dict):
                payload = {"rows": rows}
            return payload, str(path)
    return {"rows": []}, "none"


def load_market_rows() -> Dict[str, Dict[str, Any]]:
    by_symbol = {}
    for path in MARKET_CANDIDATES:
        payload = read_json(path, {})
        for row in extract_rows(payload):
            sym = safe_symbol(row)
            if sym:
                by_symbol[sym] = row
    return by_symbol


def pct_move(row: Dict[str, Any]) -> Optional[float]:
    return safe_float(row.get("day_change_pct") or row.get("day_move_percent") or row.get("day_change_percent"))


def vwap_dist(row: Dict[str, Any]) -> Optional[float]:
    return safe_float(row.get("vwap_distance_pct") or row.get("vwap_distance_percent"))


def luld_proxy(row: Dict[str, Any], market: Dict[str, Any]) -> Dict[str, Any]:
    """
    Proxy guard. This does not calculate official LULD bands.
    It flags names whose recent move/extension suggests halt/LULD caution.
    """
    merged = dict(market)
    merged.update(row)

    day = pct_move(merged)
    vwap = vwap_dist(merged)
    accel = safe_float(merged.get("volume_acceleration"))
    rvol = safe_float(merged.get("relative_volume"))
    price = safe_float(merged.get("price"))

    risk_score = 0
    flags: List[str] = []
    hard_blocks: List[str] = []

    if day is not None:
        if day >= 100:
            risk_score += 35
            hard_blocks.append("parabolic_day_move_over_100")
        elif day >= 60:
            risk_score += 20
            flags.append("large_day_move")
        elif day <= -8:
            risk_score += 15
            flags.append("sharp_downside_move")

    if vwap is not None:
        if vwap >= 12:
            risk_score += 25
            hard_blocks.append("vwap_extension_over_12")
        elif vwap >= 8:
            risk_score += 15
            flags.append("vwap_extension_over_8")

    if accel is not None and accel >= 5:
        risk_score += 15
        flags.append("extreme_volume_acceleration")

    if rvol is not None and rvol >= 15:
        risk_score += 15
        flags.append("extreme_rvol")

    if price is not None and price < 3:
        risk_score += 10
        flags.append("low_price_volatility_risk")

    if risk_score >= 60:
        hard_blocks.append("halt_luld_proxy_risk_high")

    return {
        "halt_luld_proxy_score": min(100, risk_score),
        "halt_luld_flags": flags,
        "halt_luld_hard_blocks": sorted(set(hard_blocks)),
        "halt_luld_status": "BLOCK_NEW_ENTRIES" if hard_blocks else "CAUTION" if flags else "NORMAL",
    }


def circuit_breaker_proxy(market_rows: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    declines = {}
    for sym in INDEX_SYMBOLS:
        row = market_rows.get(sym, {})
        day = pct_move(row)
        if day is not None:
            declines[sym] = day

    risk = "NORMAL"
    block = False
    flags: List[str] = []

    # Proxy thresholds using ETF move. Official MWCB is S&P 500 index based.
    # This is intentionally conservative for dashboard/order-plan blocking.
    spy = declines.get("SPY")
    if spy is not None:
        if spy <= -18:
            risk = "LEVEL_3_PROXY"
            block = True
            flags.append("spy_down_near_level_3_proxy")
        elif spy <= -12:
            risk = "LEVEL_2_PROXY"
            block = True
            flags.append("spy_down_near_level_2_proxy")
        elif spy <= -6:
            risk = "LEVEL_1_PROXY"
            block = True
            flags.append("spy_down_near_level_1_proxy")
        elif spy <= -3:
            risk = "MARKET_STRESS"
            flags.append("spy_down_more_than_3")

    return {
        "market_circuit_proxy_status": risk,
        "block_new_entries": block,
        "flags": flags,
        "index_day_changes": declines,
        "note": "Proxy guard using SPY/ETF moves. Official market-wide circuit breakers use S&P 500 index levels.",
    }


def build_guard() -> tuple[Dict[str, Any], Dict[str, Any]]:
    dashboard, source = load_dashboard()
    rows = extract_rows(dashboard)
    market_rows = load_market_rows()
    circuit = circuit_breaker_proxy(market_rows)

    enriched = []
    block_count = 0
    caution_count = 0

    for row in rows:
        sym = safe_symbol(row)
        market = market_rows.get(sym, {})
        guard = luld_proxy(row, market)

        if circuit["block_new_entries"]:
            guard["halt_luld_hard_blocks"] = sorted(set(guard["halt_luld_hard_blocks"] + ["market_circuit_proxy_blocks_new_entries"]))
            guard["halt_luld_status"] = "BLOCK_NEW_ENTRIES"

        if guard["halt_luld_status"] == "BLOCK_NEW_ENTRIES":
            block_count += 1
        elif guard["halt_luld_status"] == "CAUTION":
            caution_count += 1

        new_row = dict(row)
        new_row["market_guard"] = guard
        new_row["market_circuit_proxy"] = circuit
        enriched.append(new_row)

    dashboard["rows"] = enriched
    dashboard["schema_version"] = "signal_dashboard_market_guard_enriched_v1"
    dashboard["market_guard_generated_at"] = now_utc_iso()
    dashboard["market_guard_source"] = source
    dashboard["market_circuit_proxy"] = circuit

    payload = {
        "schema_version": "halt_luld_circuit_guard_v1",
        "generated_at": dashboard["market_guard_generated_at"],
        "status": "PASS",
        "signal_source": source,
        "counts": {
            "signals": len(enriched),
            "blocked": block_count,
            "caution": caution_count,
        },
        "market_circuit_proxy": circuit,
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "guard_only": True,
            "disclaimer": "Proxy halt/LULD/circuit guard only. Not official exchange band data. Not financial advice.",
        },
    }
    return dashboard, payload


def export_guard() -> Dict[str, Any]:
    dashboard, payload = build_guard()
    health = {
        "schema_version": "halt_luld_circuit_guard_health_v1",
        "generated_at": payload["generated_at"],
        "status": payload["status"],
        "signals": payload["counts"]["signals"],
        "blocked": payload["counts"]["blocked"],
        "caution": payload["counts"]["caution"],
        "market_circuit_proxy_status": payload["market_circuit_proxy"]["market_circuit_proxy_status"],
        "order_submission": False,
        "live_trading": False,
    }
    write_json(OUTPUT_DASHBOARD_PATH, dashboard)
    write_json(OUTPUT_DOCS_PATH, payload)
    write_json(OUTPUT_STATE_PATH, payload)
    write_json(HEALTH_PATH, health)
    return {
        "status": "PASS",
        "signals": payload["counts"]["signals"],
        "blocked": payload["counts"]["blocked"],
        "market_circuit_proxy_status": payload["market_circuit_proxy"]["market_circuit_proxy_status"],
        "output_dashboard": str(OUTPUT_DASHBOARD_PATH),
        "health_path": str(HEALTH_PATH),
    }


def main() -> None:
    print(json.dumps(export_guard(), indent=2))


if __name__ == "__main__":
    main()
