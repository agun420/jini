from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_STATE_PATH = Path("state/prediction_engine/blocked_journal.json")


@dataclass
class BlockInitParams:
    ticker: str
    blocked_price: float
    blocked_reason: str
    score: float
    vwap_dist: float
    atr: float = 0.08
    shares: int = 100
    source_alert_id: str | None = None
    setup: str | None = None


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


class BlockedJournal:
    """
    Blocked buy-order-alert journal.

    Tracks signals that were blocked or not acted on.
    This module does not place orders.
    This module does not enable paper trading.
    This module does not enable live trading.
    """

    def __init__(self, storage_path: str | Path = DEFAULT_STATE_PATH):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.storage_path.exists():
            self._write_payload(self._empty_payload())

    def _empty_payload(self) -> dict[str, Any]:
        return {
            "schema_version": "blocked_journal_v1",
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

    def initialize_block(self, params: BlockInitParams) -> str | None:
        symbol = str(params.ticker or "").upper().strip()
        blocked_price = safe_float(params.blocked_price)

        if not symbol or blocked_price <= 0:
            return None

        ts = utc_now_epoch()
        block_id = f"{symbol}_{ts}_{uuid.uuid4().hex[:8]}"

        record = {
            "block_id": block_id,
            "record_type": "BLOCKED",
            "ticker": symbol,
            "status": "PENDING_AUDIT",
            "created_at": utc_now_iso(),
            "blocked_time": ts,
            "entry_time": ts,
            "blocked_price": blocked_price,
            "blocked_reason": str(params.blocked_reason or "UNKNOWN").upper(),
            "score": safe_float(params.score),
            "vwap_dist": safe_float(params.vwap_dist),
            "atr_at_entry": safe_float(params.atr),
            "shares": safe_int(params.shares, 100),
            "setup": str(params.setup or "UNKNOWN"),
            "source_alert_id": params.source_alert_id,
            "spread_trace": [],
            "max_gain_60m": 0.0,
            "max_drawdown_60m": 0.0,
            "fillable": True,
            "final_label": "PENDING_AUDIT",
            "saved_loss": 0.0,
            "missed_gain": 0.0,
            "outcome_pnl": 0.0,
            "order_submission": False,
            "live_trading": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
        }

        payload = self._read_payload()
        records = payload.setdefault("records", {})
        records[block_id] = record
        self._write_payload(payload)

        return block_id

    def update_shadow_metrics(
        self,
        block_id: str,
        bid: float,
        ask: float,
        spread_pct: float,
        current_high: float,
        current_low: float,
    ) -> dict[str, Any] | None:
        payload = self._read_payload()
        records = payload.setdefault("records", {})

        if block_id not in records:
            return None

        block = records[block_id]
        if block.get("final_label") != "PENDING_AUDIT":
            return block

        blocked_price = safe_float(block.get("blocked_price"))
        if blocked_price <= 0:
            return block

        spread_pct = safe_float(spread_pct)

        block.setdefault("spread_trace", []).append({
            "t": utc_now_epoch(),
            "bid": safe_float(bid),
            "ask": safe_float(ask),
            "spread_pct": spread_pct,
        })

        gain_delta = (safe_float(current_high) - blocked_price) / blocked_price
        drawdown_delta = (safe_float(current_low) - blocked_price) / blocked_price

        block["max_gain_60m"] = max(safe_float(block.get("max_gain_60m")), gain_delta)
        block["max_drawdown_60m"] = min(safe_float(block.get("max_drawdown_60m")), drawdown_delta)

        if spread_pct > 0.025:
            block["fillable"] = False

        records[block_id] = block
        self._write_payload(payload)

        return block

    def audit_omission_verdict(self, block_id: str) -> str | None:
        payload = self._read_payload()
        records = payload.setdefault("records", {})

        if block_id not in records:
            return None

        block = records[block_id]

        if block.get("final_label") != "PENDING_AUDIT":
            return block.get("final_label")

        blocked_price = safe_float(block.get("blocked_price"))
        shares = safe_int(block.get("shares"), 100)
        max_gain = safe_float(block.get("max_gain_60m"))
        max_drawdown = safe_float(block.get("max_drawdown_60m"))

        block["exit_time"] = safe_int(block.get("blocked_time")) + 3600
        block["audited_at"] = utc_now_iso()

        if not block.get("fillable", True):
            block["final_label"] = "OMISSION_CORRECT_UNTRADEABLE"
        elif max_gain >= 0.15 and max_drawdown > -0.04:
            block["final_label"] = "OMISSION_ERROR_REAL_EDGE_MISSED"
            block["missed_gain"] = round(blocked_price * 0.15 * shares, 4)
        elif max_drawdown <= -0.05:
            block["final_label"] = "OMISSION_CORRECT_AVOIDED_TRAP"
            block["saved_loss"] = round(abs(blocked_price * max_drawdown * shares), 4)
        else:
            block["final_label"] = "OMISSION_CORRECT_CHOP_AVOIDANCE"

        records[block_id] = block
        self._write_payload(payload)

        return block["final_label"]

    def health(self) -> dict[str, Any]:
        records = self.list_records()

        pending = [r for r in records if r.get("final_label") == "PENDING_AUDIT"]
        missed = [r for r in records if r.get("final_label") == "OMISSION_ERROR_REAL_EDGE_MISSED"]
        saved = [r for r in records if r.get("final_label") == "OMISSION_CORRECT_AVOIDED_TRAP"]
        untradeable = [r for r in records if r.get("final_label") == "OMISSION_CORRECT_UNTRADEABLE"]
        chop = [r for r in records if r.get("final_label") == "OMISSION_CORRECT_CHOP_AVOIDANCE"]

        total_saved_loss = sum(safe_float(r.get("saved_loss")) for r in records)
        total_missed_gain = sum(safe_float(r.get("missed_gain")) for r in records)

        warnings = []
        blockers = []

        if len(records) < 30:
            warnings.append("blocked_journal_sample_below_30")

        return {
            "schema_version": "blocked_journal_health_v1",
            "generated_at": utc_now_iso(),
            "status": "PASS" if not blockers else "FAIL",
            "blockers": blockers,
            "warnings": warnings,
            "total_records": len(records),
            "pending_audit": len(pending),
            "missed_real_edge": len(missed),
            "avoided_trap": len(saved),
            "untradeable": len(untradeable),
            "chop_avoidance": len(chop),
            "total_saved_loss": round(total_saved_loss, 4),
            "total_missed_gain": round(total_missed_gain, 4),
            "order_submission": False,
            "live_trading": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
        }
