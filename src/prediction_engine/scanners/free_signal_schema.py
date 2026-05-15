from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


STATUS_TRADE_ELIGIBLE = "TRADE_ELIGIBLE"
STATUS_WAIT_FOR_PULLBACK = "WAIT_FOR_PULLBACK"
STATUS_ALERT_ONLY = "ALERT_ONLY"
STATUS_WATCH_ONLY = "WATCH_ONLY"
STATUS_NO_TRADE = "NO_TRADE"

ALL_STATUSES = {
    STATUS_TRADE_ELIGIBLE,
    STATUS_WAIT_FOR_PULLBACK,
    STATUS_ALERT_ONLY,
    STATUS_WATCH_ONLY,
    STATUS_NO_TRADE,
}


@dataclass
class DataQuality:
    primary_source: str = "unknown"
    fallback_used: bool = False
    data_age_seconds: Optional[float] = None
    quality: str = "UNKNOWN"
    notes: List[str] = field(default_factory=list)


@dataclass
class FreeSignal:
    ticker: str
    status: str
    score: float
    price: float

    gap_pct: Optional[float] = None
    day_change_pct: Optional[float] = None
    relative_volume: Optional[float] = None
    vwap: Optional[float] = None
    vwap_distance_pct: Optional[float] = None
    volume_acceleration: Optional[float] = None
    trend_state: str = "UNKNOWN"

    entry: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    risk_reward: Optional[float] = None

    reason: str = ""
    no_trade_reasons: List[str] = field(default_factory=list)
    data_quality: DataQuality = field(default_factory=DataQuality)

    source_type: str = "free_scanner_normalizer"
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)

        if self.status not in ALL_STATUSES:
            payload["status"] = STATUS_NO_TRADE
            payload["no_trade_reasons"] = list(payload.get("no_trade_reasons") or []) + [
                f"invalid_status:{self.status}"
            ]

        return payload


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def safe_symbol(row: Dict[str, Any]) -> str:
    return str(
        row.get("ticker")
        or row.get("symbol")
        or row.get("S")
        or row.get("T")
        or ""
    ).upper().strip()


def pct(current: Optional[float], base: Optional[float]) -> Optional[float]:
    if current is None or base in (None, 0):
        return None

    try:
        return (float(current) - float(base)) / float(base) * 100.0
    except Exception:
        return None


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))
