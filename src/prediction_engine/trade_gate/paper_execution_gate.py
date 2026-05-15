from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import Request, urlopen


SIGNAL_CANDIDATES = [
    Path("docs/data/prediction_engine/signal_dashboard_market_guard_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_quality_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_news_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_finra_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard.json"),
]

ADAPTIVE_GUARD_PATH = Path("docs/data/prediction_engine/adaptive_guard.json")

ORDER_PLAN_STATE_PATH = Path("state/prediction_engine/paper_order_plan.json")
ORDER_PLAN_DOCS_PATH = Path("docs/data/prediction_engine/paper_order_plan.json")
ORDER_GATE_HEALTH_PATH = Path("docs/data/prediction_engine/paper_execution_gate_health.json")

BASE_MAX_NOTIONAL = 2000.0
MIN_PRICE = 3.0
MAX_ONE_NEW_ORDER_PER_RUN = True
MAX_OPEN_POSITIONS = 1
ALLOWED_STATUS = "TRADE_ELIGIBLE"
DEFAULT_MIN_SCORE = 85.0

ORDER_SUBMISSION_ENABLED = os.getenv("PAPER_ORDER_SUBMISSION_ENABLED", "false").lower() == "true"


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
        for key in ("rows", "signals", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

    return []


def load_signal_rows() -> Tuple[List[Dict[str, Any]], str]:
    for path in SIGNAL_CANDIDATES:
        payload = read_json(path, {})
        rows = extract_rows(payload)
        if rows:
            return rows, str(path)

    return [], "none"


def load_guard() -> Dict[str, Any]:
    payload = read_json(ADAPTIVE_GUARD_PATH, {})
    guard = payload.get("guard") if isinstance(payload.get("guard"), dict) else {}

    return {
        "allow_new_entries": bool(guard.get("allow_new_entries", True)),
        "risk_mode": guard.get("risk_mode", "UNKNOWN"),
        "min_score_required": safe_float(guard.get("min_score_required"), DEFAULT_MIN_SCORE) or DEFAULT_MIN_SCORE,
        "max_notional_per_trade": safe_float(guard.get("max_notional_per_trade"), BASE_MAX_NOTIONAL) or BASE_MAX_NOTIONAL,
        "reasons": guard.get("reasons") if isinstance(guard.get("reasons"), list) else [],
        "source_loaded": bool(payload),
    }


def alpaca_headers() -> Optional[Dict[str, str]]:
    key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
    secret = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")

    if not key or not secret:
        return None

    return {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "Content-Type": "application/json",
    }


def alpaca_base_url() -> str:
    # Paper endpoint only. No live endpoint is supported by this gate.
    return "https://paper-api.alpaca.markets"


def fetch_paper_account_snapshot(headers: Optional[Dict[str, str]]) -> Dict[str, Any]:
    if not headers:
        return {
            "available": False,
            "reason": "missing_alpaca_keys",
            "open_position_count": None,
            "open_order_count": None,
            "buying_power": None,
        }

    base = alpaca_base_url()

    account: Dict[str, Any] = {}
    positions: List[Any] = []
    orders: List[Any] = []

    try:
        req = Request(f"{base}/v2/account", headers=headers, method="GET")
        with urlopen(req, timeout=20) as response:
            account = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {
            "available": False,
            "reason": f"account_fetch_failed:{exc}",
            "open_position_count": None,
            "open_order_count": None,
            "buying_power": None,
        }

    try:
        req = Request(f"{base}/v2/positions", headers=headers, method="GET")
        with urlopen(req, timeout=20) as response:
            positions = json.loads(response.read().decode("utf-8"))
            if not isinstance(positions, list):
                positions = []
    except Exception:
        positions = []

    try:
        req = Request(f"{base}/v2/orders?status=open&limit=100", headers=headers, method="GET")
        with urlopen(req, timeout=20) as response:
            orders = json.loads(response.read().decode("utf-8"))
            if not isinstance(orders, list):
                orders = []
    except Exception:
        orders = []

    return {
        "available": True,
        "reason": "loaded",
        "open_position_count": len(positions),
        "open_order_count": len(orders),
        "buying_power": safe_float(account.get("buying_power")),
        "cash": safe_float(account.get("cash")),
        "equity": safe_float(account.get("equity")),
        "paper_account_status": account.get("status"),
        "positions": [
            {
                "symbol": item.get("symbol"),
                "qty": item.get("qty"),
                "market_value": item.get("market_value"),
                "unrealized_pl": item.get("unrealized_pl"),
                "unrealized_plpc": item.get("unrealized_plpc"),
            }
            for item in positions[:20]
            if isinstance(item, dict)
        ],
        "open_orders": [
            {
                "symbol": item.get("symbol"),
                "side": item.get("side"),
                "type": item.get("type"),
                "qty": item.get("qty"),
                "status": item.get("status"),
            }
            for item in orders[:20]
            if isinstance(item, dict)
        ],
    }


def normalize_signal(row: Dict[str, Any]) -> Dict[str, Any]:
    ticker = safe_symbol(row)

    price = safe_float(row.get("price"))
    entry = safe_float(row.get("entry"), price)
    stop = safe_float(row.get("stop"))
    target = safe_float(row.get("target"))
    score = safe_float(row.get("score"), 0.0) or 0.0
    risk_reward = safe_float(row.get("risk_reward"))

    return {
        "ticker": ticker,
        "status": str(row.get("status") or row.get("signal") or "UNKNOWN"),
        "score": score,
        "price": price,
        "entry": entry,
        "stop": stop,
        "target": target,
        "risk_reward": risk_reward,
        "relative_volume": safe_float(row.get("relative_volume")),
        "vwap_distance_percent": safe_float(row.get("vwap_distance_percent") or row.get("vwap_distance_pct")),
        "reason": row.get("trade_gate_summary") or row.get("reason") or "",
        "no_trade_reasons": row.get("no_trade_reasons") if isinstance(row.get("no_trade_reasons"), list) else [],
        "raw": row,
    }


def choose_best_candidate(rows: List[Dict[str, Any]], guard: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    reasons: List[str] = []

    min_score = guard["min_score_required"]
    candidates: List[Dict[str, Any]] = []

    for row in rows:
        signal = normalize_signal(row)

        if not signal["ticker"]:
            continue

        blocks = validate_signal(signal, guard, account_snapshot=None, lightweight=True)

        if blocks:
            continue

        candidates.append(signal)

    if not candidates:
        reasons.append("no_signal_passed_trade_eligible_gate")
        return None, reasons

    candidates.sort(
        key=lambda item: (
            float(item.get("score") or 0),
            float(item.get("relative_volume") or 0),
            float(item.get("risk_reward") or 0),
        ),
        reverse=True,
    )

    return candidates[0], reasons


def validate_signal(
    signal: Dict[str, Any],
    guard: Dict[str, Any],
    account_snapshot: Optional[Dict[str, Any]],
    lightweight: bool = False,
) -> List[str]:
    blocks: List[str] = []

    ticker = signal.get("ticker")
    status = signal.get("status")
    score = safe_float(signal.get("score"), 0.0) or 0.0
    price = safe_float(signal.get("price"))
    entry = safe_float(signal.get("entry"), price)
    stop = safe_float(signal.get("stop"))
    target = safe_float(signal.get("target"))
    risk_reward = safe_float(signal.get("risk_reward"))

    if not ticker:
        blocks.append("missing_ticker")

    if status != ALLOWED_STATUS:
        blocks.append(f"status_not_allowed:{status}")

    quality_status = (signal.get("raw") or {}).get("quality_gate_status") or signal.get("quality_gate_status")
    if quality_status and quality_status not in {"QUALITY_APPROVED", "QUALITY_CAUTION"}:
        blocks.append(f"quality_gate_blocks:{quality_status}")

    quality = (signal.get("raw") or {}).get("advanced_quality") or {}
    if isinstance(quality, dict):
        if quality.get("quality_gate_status") == "QUALITY_BLOCKED":
            blocks.append("advanced_quality_gate_blocked")
        for block in quality.get("quality_gate_blocks") or []:
            blocks.append(f"quality_block:{block}")

    market_guard = (signal.get("raw") or {}).get("market_guard") or {}
    if isinstance(market_guard, dict):
        if market_guard.get("halt_luld_status") == "BLOCK_NEW_ENTRIES":
            blocks.append("market_guard_blocks_new_entries")
        for block in market_guard.get("halt_luld_hard_blocks") or []:
            blocks.append(f"market_guard_block:{block}")

    circuit = (signal.get("raw") or {}).get("market_circuit_proxy") or {}
    if isinstance(circuit, dict) and circuit.get("block_new_entries"):
        blocks.append("market_circuit_proxy_blocks_new_entries")

    if not guard.get("allow_new_entries", True):
        blocks.append("adaptive_guard_blocks_new_entries")

    if score < guard.get("min_score_required", DEFAULT_MIN_SCORE):
        blocks.append("score_below_adaptive_minimum")

    if price is None or price < MIN_PRICE:
        blocks.append("price_below_minimum_or_missing")

    if entry is None or entry <= 0:
        blocks.append("missing_entry")

    if stop is None or stop <= 0:
        blocks.append("missing_stop")

    if target is None or target <= 0:
        blocks.append("missing_target")

    if risk_reward is None or risk_reward < 2:
        blocks.append("risk_reward_below_2")

    if stop is not None and entry is not None and stop >= entry:
        blocks.append("stop_not_below_entry")

    if target is not None and entry is not None and target <= entry:
        blocks.append("target_not_above_entry")

    if lightweight:
        return blocks

    if account_snapshot:
        if account_snapshot.get("available"):
            if int(account_snapshot.get("open_position_count") or 0) >= MAX_OPEN_POSITIONS:
                blocks.append("max_open_positions_reached")

            if int(account_snapshot.get("open_order_count") or 0) > 0:
                blocks.append("open_orders_exist")

            symbols_held = {
                str(item.get("symbol") or "").upper()
                for item in account_snapshot.get("positions", [])
                if isinstance(item, dict)
            }

            if ticker in symbols_held:
                blocks.append("ticker_already_held")

            buying_power = safe_float(account_snapshot.get("buying_power"))
            if buying_power is not None and buying_power < min(guard["max_notional_per_trade"], BASE_MAX_NOTIONAL):
                blocks.append("buying_power_below_required_notional")
        else:
            # Missing Alpaca account should block actual submission but not planning.
            blocks.append(f"account_snapshot_unavailable:{account_snapshot.get('reason')}")

    return blocks


def create_order_plan(signal: Optional[Dict[str, Any]], guard: Dict[str, Any], account_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    if not signal:
        return {
            "created": False,
            "reason": "no_candidate",
            "order": None,
        }

    blocks = validate_signal(signal, guard, account_snapshot=account_snapshot, lightweight=False)

    if blocks:
        return {
            "created": False,
            "reason": "blocked_by_gate",
            "blocks": blocks,
            "candidate": signal,
            "order": None,
        }

    entry = safe_float(signal.get("entry") or signal.get("price"))
    stop = safe_float(signal.get("stop"))
    target = safe_float(signal.get("target"))
    max_notional = min(safe_float(guard.get("max_notional_per_trade"), BASE_MAX_NOTIONAL) or BASE_MAX_NOTIONAL, BASE_MAX_NOTIONAL)

    qty = math.floor(max_notional / entry) if entry and entry > 0 else 0

    if qty < 1:
        return {
            "created": False,
            "reason": "quantity_below_1",
            "candidate": signal,
            "order": None,
        }

    notional = round(qty * entry, 2)

    order = {
        "symbol": signal["ticker"],
        "qty": qty,
        "side": "buy",
        "type": "market",
        "time_in_force": "day",
        "order_class": "bracket",
        "take_profit": {
            "limit_price": round(target, 2),
        },
        "stop_loss": {
            "stop_price": round(stop, 2),
        },
        "estimated_entry": round(entry, 4),
        "estimated_notional": notional,
        "paper_only": True,
    }

    return {
        "created": True,
        "reason": "paper_order_plan_created_submission_disabled_by_default",
        "candidate": signal,
        "order": order,
    }


def submit_order_if_enabled(order_plan: Dict[str, Any], headers: Optional[Dict[str, str]]) -> Dict[str, Any]:
    if not ORDER_SUBMISSION_ENABLED:
        return {
            "submitted": False,
            "reason": "PAPER_ORDER_SUBMISSION_ENABLED_is_false",
            "response": None,
        }

    if not headers:
        return {
            "submitted": False,
            "reason": "missing_alpaca_keys",
            "response": None,
        }

    if not order_plan.get("created") or not order_plan.get("order"):
        return {
            "submitted": False,
            "reason": "no_valid_order_plan",
            "response": None,
        }

    # One final hard block. This gate only supports paper endpoint.
    base = alpaca_base_url()
    body = json.dumps(order_plan["order"]).encode("utf-8")

    try:
        request = Request(
            f"{base}/v2/orders",
            data=body,
            headers=headers,
            method="POST",
        )

        with urlopen(request, timeout=20) as response:
            response_payload = json.loads(response.read().decode("utf-8"))

        return {
            "submitted": True,
            "reason": "paper_order_submitted",
            "response": response_payload,
        }
    except Exception as exc:
        return {
            "submitted": False,
            "reason": f"paper_order_submit_failed:{exc}",
            "response": None,
        }


def build_paper_gate_payload() -> Dict[str, Any]:
    rows, signal_source = load_signal_rows()
    guard = load_guard()
    headers = alpaca_headers()
    account_snapshot = fetch_paper_account_snapshot(headers)

    best, choose_reasons = choose_best_candidate(rows, guard)
    order_plan = create_order_plan(best, guard, account_snapshot)
    submission = submit_order_if_enabled(order_plan, headers)

    payload = {
        "schema_version": "paper_execution_gate_v1",
        "generated_at": now_utc_iso(),
        "status": "PASS",
        "mode": "paper_only_order_plan",
        "signal_source": signal_source,
        "adaptive_guard_loaded": guard.get("source_loaded"),
        "adaptive_guard": guard,
        "account_snapshot": {
            key: value
            for key, value in account_snapshot.items()
            if key not in {"positions", "open_orders"}
        },
        "positions": account_snapshot.get("positions", []),
        "open_orders": account_snapshot.get("open_orders", []),
        "candidate_selection_reasons": choose_reasons,
        "selected_candidate": best,
        "order_plan": order_plan,
        "submission": submission,
        "safety": {
            "paper_only": True,
            "live_trading": False,
            "short_selling": False,
            "options": False,
            "order_submission_enabled": ORDER_SUBMISSION_ENABLED,
            "order_submission_default": False,
            "allowed_status": ALLOWED_STATUS,
            "max_notional_hard_cap": BASE_MAX_NOTIONAL,
            "max_open_positions": MAX_OPEN_POSITIONS,
            "max_one_new_order_per_run": MAX_ONE_NEW_ORDER_PER_RUN,
            "disclaimer": "Paper execution gate is for research/paper use only. Not financial advice.",
        },
    }

    return payload


def export_paper_gate() -> Dict[str, Any]:
    payload = build_paper_gate_payload()

    health = {
        "schema_version": "paper_execution_gate_health_v1",
        "generated_at": payload["generated_at"],
        "status": payload["status"],
        "order_plan_created": payload["order_plan"].get("created", False),
        "order_submission_enabled": ORDER_SUBMISSION_ENABLED,
        "order_submitted": payload["submission"].get("submitted", False),
        "selected_ticker": (payload.get("selected_candidate") or {}).get("ticker"),
        "risk_mode": payload["adaptive_guard"].get("risk_mode"),
        "allow_new_entries": payload["adaptive_guard"].get("allow_new_entries"),
        "account_available": payload["account_snapshot"].get("available"),
        "signal_source": payload["signal_source"],
        "paper_only": True,
        "notes": [
            "Package 7 creates a paper order plan only by default.",
            "Actual submission requires PAPER_ORDER_SUBMISSION_ENABLED=true and Alpaca paper keys.",
            "Live trading is not supported.",
            "Only TRADE_ELIGIBLE can pass the gate.",
        ],
    }

    write_json(ORDER_PLAN_STATE_PATH, payload)
    write_json(ORDER_PLAN_DOCS_PATH, payload)
    write_json(ORDER_GATE_HEALTH_PATH, health)

    return {
        "status": "PASS",
        "order_plan_created": payload["order_plan"].get("created", False),
        "order_submission_enabled": ORDER_SUBMISSION_ENABLED,
        "order_submitted": payload["submission"].get("submitted", False),
        "selected_ticker": (payload.get("selected_candidate") or {}).get("ticker"),
        "output_state": str(ORDER_PLAN_STATE_PATH),
        "output_docs": str(ORDER_PLAN_DOCS_PATH),
        "health_path": str(ORDER_GATE_HEALTH_PATH),
    }


def main() -> None:
    print(json.dumps(export_paper_gate(), indent=2))


if __name__ == "__main__":
    main()
