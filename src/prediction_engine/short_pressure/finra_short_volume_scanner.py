from __future__ import annotations

import csv
import json
import os
import re
import time
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SHORT_PRESSURE_PATH = Path("docs/data/prediction_engine/finra_short_pressure.json")
HEALTH_PATH = Path("docs/data/prediction_engine/finra_short_pressure_health.json")
CACHE_PATH = Path("state/prediction_engine/finra_short_volume_cache.json")

CANDIDATE_PATHS = [
    Path("docs/data/prediction_engine/free_scanner_enriched.json"),
    Path("docs/data/prediction_engine/free_scanner.json"),
    Path("docs/data/prediction_engine/signal_dashboard_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard.json"),
    Path("state/prediction_engine/dynamic_alpaca_candidates.json"),
]

FINRA_REGSHO_BASE = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{date}.txt"


@dataclass
class FinraShortPressure:
    ticker: str
    source: str
    trade_date: Optional[str]
    short_volume: Optional[int]
    short_exempt_volume: Optional[int]
    total_volume: Optional[int]
    short_volume_ratio: Optional[float]
    short_pressure_score: float
    short_pressure_label: str
    notes: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


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


def safe_symbol(value: Any) -> str:
    text = str(value or "").upper().strip()
    text = re.sub(r"[^A-Z0-9.\-]", "", text)
    return text


def extract_rows(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "signals", "candidates", "predictions", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def extract_symbols() -> List[str]:
    symbols: List[str] = []
    seen = set()
    for path in CANDIDATE_PATHS:
        payload = read_json(path, {})
        for row in extract_rows(payload):
            sym = safe_symbol(row.get("ticker") or row.get("symbol"))
            if sym and sym not in seen:
                seen.add(sym)
                symbols.append(sym)
    return symbols[:250]


def recent_weekdays(max_days: int = 7) -> List[str]:
    # FINRA files publish by trading date. Try recent weekdays because today's file may not exist yet.
    out: List[str] = []
    now = datetime.now(timezone.utc).date()
    cursor = now
    while len(out) < max_days:
        if cursor.weekday() < 5:
            out.append(cursor.strftime("%Y%m%d"))
        cursor -= timedelta(days=1)
    return out


def fetch_url(url: str, timeout: int = 20) -> Optional[str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": os.environ.get("FINRA_USER_AGENT", "free-scanner-finra-layer/1.0"),
            "Accept": "text/plain,*/*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                return None
            return response.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def parse_finra_pipe_file(text: str, trade_date: str) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return rows

    reader = csv.DictReader(lines, delimiter="|")
    for row in reader:
        symbol = safe_symbol(row.get("Symbol"))
        if not symbol:
            continue
        try:
            short_volume = int(row.get("ShortVolume") or 0)
            short_exempt = int(row.get("ShortExemptVolume") or 0)
            total_volume = int(row.get("TotalVolume") or 0)
        except Exception:
            continue

        rows[symbol] = {
            "ticker": symbol,
            "trade_date": trade_date,
            "short_volume": short_volume,
            "short_exempt_volume": short_exempt,
            "total_volume": total_volume,
        }
    return rows


def load_cached_finra() -> Dict[str, Any]:
    cache = read_json(CACHE_PATH, {})
    return cache if isinstance(cache, dict) else {}


def save_cached_finra(trade_date: str, rows: Dict[str, Dict[str, Any]]) -> None:
    cache = {
        "schema_version": "finra_short_volume_cache_v1",
        "updated_at": now_utc_iso(),
        "trade_date": trade_date,
        "rows": rows,
    }
    write_json(CACHE_PATH, cache)


def load_latest_finra_rows() -> Tuple[Optional[str], Dict[str, Dict[str, Any]], List[str]]:
    notes: List[str] = []

    for date in recent_weekdays(7):
        url = FINRA_REGSHO_BASE.format(date=date)
        text = fetch_url(url)
        if not text:
            notes.append(f"unavailable:{date}")
            continue
        rows = parse_finra_pipe_file(text, date)
        if rows:
            save_cached_finra(date, rows)
            notes.append(f"loaded:{date}")
            return date, rows, notes

    cache = load_cached_finra()
    cached_rows = cache.get("rows") if isinstance(cache.get("rows"), dict) else {}
    cached_date = cache.get("trade_date")
    if cached_rows:
        notes.append("used_cache")
        return cached_date, cached_rows, notes

    notes.append("no_finra_data_available")
    return None, {}, notes


def score_short_pressure(short_volume: Optional[int], total_volume: Optional[int]) -> Tuple[Optional[float], float, str, List[str]]:
    notes: List[str] = []
    if not total_volume or total_volume <= 0 or short_volume is None:
        return None, 0.0, "NO_DATA", ["missing_finra_volume"]

    ratio = short_volume / total_volume
    # Context-only score. Capped low so it cannot dominate scanner status.
    if ratio >= 0.65:
        return round(ratio, 4), 12.0, "ELEVATED", ["high_short_sale_volume_ratio"]
    if ratio >= 0.50:
        return round(ratio, 4), 8.0, "MODERATE", ["moderate_short_sale_volume_ratio"]
    if ratio >= 0.35:
        return round(ratio, 4), 4.0, "NORMAL", ["normal_short_sale_volume_ratio"]
    return round(ratio, 4), 1.0, "LOW", ["low_short_sale_volume_ratio"]


def build_short_pressure_payload() -> Dict[str, Any]:
    symbols = extract_symbols()
    trade_date, finra_rows, load_notes = load_latest_finra_rows()

    pressure_rows: List[Dict[str, Any]] = []
    for symbol in symbols:
        item = finra_rows.get(symbol)
        if item:
            ratio, score, label, notes = score_short_pressure(item.get("short_volume"), item.get("total_volume"))
            pressure = FinraShortPressure(
                ticker=symbol,
                source="FINRA_REGSHO_DAILY_CNMS",
                trade_date=item.get("trade_date"),
                short_volume=item.get("short_volume"),
                short_exempt_volume=item.get("short_exempt_volume"),
                total_volume=item.get("total_volume"),
                short_volume_ratio=ratio,
                short_pressure_score=score,
                short_pressure_label=label,
                notes=notes,
            )
        else:
            pressure = FinraShortPressure(
                ticker=symbol,
                source="FINRA_REGSHO_DAILY_CNMS",
                trade_date=trade_date,
                short_volume=None,
                short_exempt_volume=None,
                total_volume=None,
                short_volume_ratio=None,
                short_pressure_score=0.0,
                short_pressure_label="NO_DATA",
                notes=["symbol_not_found_in_latest_finra_file"],
            )
        pressure_rows.append(pressure.to_dict())

    pressure_rows.sort(key=lambda x: float(x.get("short_pressure_score") or 0), reverse=True)

    counts = {
        "symbols_checked": len(symbols),
        "rows_with_finra_data": sum(1 for x in pressure_rows if x.get("total_volume") is not None),
        "elevated": sum(1 for x in pressure_rows if x.get("short_pressure_label") == "ELEVATED"),
        "moderate": sum(1 for x in pressure_rows if x.get("short_pressure_label") == "MODERATE"),
        "no_data": sum(1 for x in pressure_rows if x.get("short_pressure_label") == "NO_DATA"),
    }

    return {
        "schema_version": "finra_short_pressure_v1",
        "generated_at": now_utc_iso(),
        "status": "PASS" if symbols else "NO_SYMBOLS",
        "source": "FINRA Reg SHO Daily Short Sale Volume file",
        "trade_date": trade_date,
        "counts": counts,
        "rows": pressure_rows,
        "notes": load_notes + [
            "FINRA short-sale volume is delayed context only.",
            "This layer never triggers a buy by itself.",
            "High short-sale volume is not the same as live short interest or cost to borrow.",
        ],
        "safety": {
            "order_submission": False,
            "paper_only": True,
            "score_boost_only": True,
            "max_short_pressure_score": 12,
        },
    }


def export_short_pressure() -> Dict[str, Any]:
    payload = build_short_pressure_payload()
    write_json(SHORT_PRESSURE_PATH, payload)

    health = {
        "schema_version": "finra_short_pressure_health_v1",
        "generated_at": payload["generated_at"],
        "status": payload["status"],
        "trade_date": payload.get("trade_date"),
        "symbols_checked": payload.get("counts", {}).get("symbols_checked", 0),
        "rows_with_finra_data": payload.get("counts", {}).get("rows_with_finra_data", 0),
        "order_submission": False,
        "paper_only": True,
        "notes": payload.get("notes", []),
    }
    write_json(HEALTH_PATH, health)

    return {
        "status": payload["status"],
        "output_path": str(SHORT_PRESSURE_PATH),
        "health_path": str(HEALTH_PATH),
        "symbols_checked": payload.get("counts", {}).get("symbols_checked", 0),
        "rows_with_finra_data": payload.get("counts", {}).get("rows_with_finra_data", 0),
    }


def main() -> None:
    print(json.dumps(export_short_pressure(), indent=2))


if __name__ == "__main__":
    main()
