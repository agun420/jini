"""Shared low-level utilities for the prediction engine."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


now_utc_iso = utc_now_iso


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        x = float(value)
        return default if (math.isnan(x) or math.isinf(x)) else x
    except Exception:
        return default


def safe_float_opt(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        x = float(value)
        return default if (math.isnan(x) or math.isinf(x)) else x
    except Exception:
        return default


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def safe_symbol(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "signals", "candidates", "history", "events", "items", "records", "data", "predictions"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def read_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = {}
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
