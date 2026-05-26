from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class OpenTradeRequest:
    ticker: str
    entry_signal_price: float
    execution_layers: list[dict[str, Any]]
    atr: float
    vwap_dist: float
    score: float
    regime: str
    shares: int = 100
    source_alert_id: str | None = None
    setup: str | None = None


DEFAULT_STATE_PATH = Path("state/prediction_engine/trade_journal.json")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_now_epoch() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        x = float(value)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


class TradeJournal:
    """
    Paper/simulated trade ledger.

    This module does not place orders.
    This module does not connect to a broker.
    This module does not enable live trading.
    """

    def __init__(self, storage_path: str | Path = DEFAULT_STATE_PATH):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.storage_path.exists():
            self._write_payload(self._empty_payload())

    def _empty_payload(self) -> dict[str, Any]:
        return {
            "schema_version": "trade_journal_v1",
            "created_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
            "records": {},
            "safety": {
                "paper_only": True,
                "order_submission": False,
                "live_trading": False,
                "auto_config_overwrite": False,
            },
        }

    def _read_payload(self) -> dict[str, Any]:
        try:
            raw = self.storage_path.read_text(encoding="utf-8").strip()
            if not raw:
                return self._empty_payload()
            data = json.loads(raw)
            if not isinstance(data, dict):
                return self._empty_payload()
            data.setdefault("records", {})
            return data
        except Exception:
            return self._empty_payload()

    def _write_payload(self, payload: dict[str, Any]) -> None:
        payload["updated_at"] = utc_now_iso()
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def list_records(self) -> list[dict[str, Any]]:
        payload = self._read_payload()
        records = payload.get("records", {})
        if not isinstance(records, dict):
            return []
        return list(records.values())

    def open_trade(
        self,
        request: OpenTradeRequest,
    ) -> str:
        """
        Create a paper/simulated trade record.

        execution_layers example:
        [
          {"name": "signal_fill", "weight": 1.0, "fill": 12.34}
        ]
        """

        symbol = str(request.ticker or "").upper().strip()
        if not symbol:
            raise ValueError("ticker is required")

        entry_signal_price = safe_float(request.entry_signal_price)
        if entry_signal_price <= 0:
            raise ValueError("entry_signal_price must be greater than 0")

        if not request.execution_layers:
            raise ValueError("execution_layers must not be empty")

        clean_layers = []
        total_weight = 0.0

        for layer in request.execution_layers:
            name = str(layer.get("name") or "layer")
            weight = safe_float(layer.get("weight"))
            fill = safe_float(layer.get("fill"))

            if weight <= 0:
                raise ValueError(f"layer {name} has invalid weight")
            if fill <= 0:
                raise ValueError(f"layer {name} has invalid fill")

            total_weight += weight
            clean_layers.append({
                "name": name,
                "weight": weight,
                "fill": fill,
            })

        if abs(total_weight - 1.0) > 0.001:
            raise ValueError(f"Execution layer weights must equal 1.0. Current: {total_weight}")

        blended_average_cost = sum(layer["weight"] * layer["fill"] for layer in clean_layers)

        shares = safe_int(request.shares, 0)
        if shares <= 0:
            raise ValueError("shares must be greater than 0")

        ts = utc_now_epoch()
        trade_id = f"{symbol}_{ts}_{uuid.uuid4().hex[:8]}"

        record = {
            "trade_id": trade_id,
            "record_type": "TRADE",
            "ticker": symbol,
            "side": "LONG",
            "status": "OPEN",
            "created_at": utc_now_iso(),
            "entry_time": ts,
            "entry_signal_price": entry_signal_price,
            "execution_layers": clean_layers,
            "blended_average_cost": round(blended_average_cost, 6),
            "atr_at_entry": safe_float(request.atr),
            "vwap_dist": safe_float(request.vwap_dist),
            "score": safe_float(request.score),
            "regime": str(request.regime or "UNKNOWN").upper(),
            "setup": str(request.setup or "UNKNOWN"),
            "shares": shares,
            "source_alert_id": request.source_alert_id,
            "exit_time": None,
            "exit_fill": None,
            "outcome_pnl": None,
            "outcome_return_pct": None,
            "order_submission": False,
            "live_trading": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
        }

        payload = self._read_payload()
        records = payload.setdefault("records", {})
        records[trade_id] = record
        self._write_payload(payload)

        return trade_id

    def close_trade(self, trade_id: str, exit_fill: float) -> dict[str, Any]:
        payload = self._read_payload()
        records = payload.setdefault("records", {})

        if trade_id not in records:
            raise KeyError(f"Trade ID {trade_id} not found in trade journal")

        trade = records[trade_id]

        if trade.get("status") != "OPEN":
            return trade

        exit_fill = safe_float(exit_fill)
        if exit_fill <= 0:
            raise ValueError("exit_fill must be greater than 0")

        avg_cost = safe_float(trade.get("blended_average_cost"))
        shares = safe_int(trade.get("shares"))

        price_delta = exit_fill - avg_cost
        outcome_pnl = price_delta * shares
        outcome_return_pct = ((exit_fill - avg_cost) / avg_cost) * 100 if avg_cost > 0 else 0.0

        trade["exit_time"] = utc_now_epoch()
        trade["exit_fill"] = round(exit_fill, 6)
        trade["outcome_pnl"] = round(outcome_pnl, 4)
        trade["outcome_return_pct"] = round(outcome_return_pct, 4)
        trade["status"] = "CLOSED"
        trade["closed_at"] = utc_now_iso()

        records[trade_id] = trade
        self._write_payload(payload)

        return trade

    def health(self) -> dict[str, Any]:
        records = self.list_records()

        open_trades = [r for r in records if r.get("status") == "OPEN"]
        closed_trades = [r for r in records if r.get("status") == "CLOSED"]

        total_pnl = sum(safe_float(r.get("outcome_pnl")) for r in closed_trades)
        winners = [r for r in closed_trades if safe_float(r.get("outcome_pnl")) > 0]
        losers = [r for r in closed_trades if safe_float(r.get("outcome_pnl")) < 0]

        blockers = []
        warnings = []

        if len(closed_trades) < 30:
            warnings.append("closed_trade_sample_below_forward_validation_minimum_30")

        return {
            "schema_version": "trade_journal_health_v1",
            "generated_at": utc_now_iso(),
            "status": "PASS" if not blockers else "FAIL",
            "blockers": blockers,
            "warnings": warnings,
            "total_records": len(records),
            "open_trades": len(open_trades),
            "closed_trades": len(closed_trades),
            "winning_trades": len(winners),
            "losing_trades": len(losers),
            "total_closed_pnl": round(total_pnl, 4),
            "win_rate_pct": round((len(winners) / len(closed_trades)) * 100, 2) if closed_trades else 0,
            "forward_validation_ready": len(closed_trades) >= 30,
            "order_submission": False,
            "live_trading": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
        }
