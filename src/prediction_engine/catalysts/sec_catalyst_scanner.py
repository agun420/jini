from __future__ import annotations

import gzip
import json
import os
import time
import threading
import concurrent.futures
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.request import Request, urlopen


OUTPUT_PATH = Path("docs/data/prediction_engine/sec_catalysts.json")
HEALTH_PATH = Path("docs/data/prediction_engine/sec_catalyst_health.json")
STATE_PATH = Path("state/prediction_engine/sec_catalysts.json")

SIGNAL_INPUT_CANDIDATES = [
    Path("docs/data/prediction_engine/signal_dashboard_market_guard_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_quality_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_news_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_finra_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard.json"),
    Path("docs/data/prediction_engine/alpaca_paid_market_candidates.json"),
    Path("state/prediction_engine/dynamic_alpaca_candidates.json"),
]

SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"

CATALYST_FORMS = {"8-K", "10-Q", "10-K", "S-1", "S-3", "424B", "424B5", "DEF 14A", "SC 13G", "SC 13D"}
RISK_FORMS = {"S-1", "S-3", "424B", "424B5"}


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


def extract_rows(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]

    if isinstance(payload, dict):
        for key in ["rows", "signals", "candidates", "data", "items"]:
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]

    return []


def load_symbols(limit: int = 50) -> List[str]:
    for path in SIGNAL_INPUT_CANDIDATES:
        payload = read_json(path, {})
        rows = extract_rows(payload)
        symbols = []
        for row in rows:
            ticker = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
            if ticker:
                symbols.append(ticker)
        if symbols:
            return sorted(set(symbols))[:limit]
    return []


def sec_headers() -> Dict[str, str]:
    user_agent = os.getenv("SEC_USER_AGENT", "").strip()
    if not user_agent:
        user_agent = "scanner-engine contact@example.com"

    return {
        "User-Agent": user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Accept": "application/json,text/plain,*/*",
    }


def fetch_url_bytes(url: str) -> bytes:
    req = Request(url, headers=sec_headers(), method="GET")
    with urlopen(req, timeout=30) as resp:
        raw = resp.read()
        encoding = resp.headers.get("Content-Encoding", "").lower()

    if encoding == "gzip" or raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw)

    return raw


def fetch_json(url: str) -> Any:
    raw = fetch_url_bytes(url)
    text = raw.decode("utf-8", errors="replace")
    return json.loads(text)


def load_ticker_map() -> Dict[str, str]:
    payload = fetch_json(SEC_TICKER_URL)

    ticker_to_cik: Dict[str, str] = {}

    if isinstance(payload, dict):
        for _, item in payload.items():
            if not isinstance(item, dict):
                continue
            ticker = str(item.get("ticker") or "").upper().strip()
            cik = item.get("cik_str")
            if ticker and cik:
                ticker_to_cik[ticker] = str(cik).zfill(10)

    return ticker_to_cik


def fetch_company_submissions(cik: str) -> Dict[str, Any]:
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    return fetch_json(url)


def summarize_filings(symbol: str, cik: str, submissions: Dict[str, Any]) -> Dict[str, Any]:
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", []) if isinstance(recent, dict) else []
    dates = recent.get("filingDate", []) if isinstance(recent, dict) else []
    accessions = recent.get("accessionNumber", []) if isinstance(recent, dict) else []

    rows = []
    risk_flags = []
    catalyst_flags = []

    for idx, form in enumerate(forms[:20]):
        form = str(form)
        filing_date = dates[idx] if idx < len(dates) else None
        accession = accessions[idx] if idx < len(accessions) else None

        if form in CATALYST_FORMS:
            catalyst_flags.append(form)

        if form in RISK_FORMS:
            risk_flags.append(f"possible_dilution_or_offering:{form}")

        rows.append({
            "ticker": symbol,
            "cik": cik,
            "form": form,
            "filing_date": filing_date,
            "accession_number": accession,
            "is_catalyst_form": form in CATALYST_FORMS,
            "is_risk_form": form in RISK_FORMS,
        })

    return {
        "ticker": symbol,
        "cik": cik,
        "latest_form": rows[0]["form"] if rows else None,
        "latest_filing_date": rows[0]["filing_date"] if rows else None,
        "catalyst_forms": sorted(set(catalyst_flags)),
        "risk_flags": sorted(set(risk_flags)),
        "filings": rows,
        "sec_status": "LOADED" if rows else "NO_RECENT_FILINGS",
    }


def _process_symbol(
    symbol: str,
    cik: str,
    rate_lock: threading.Lock,
    last_time_ref: List[float]
) -> Tuple[Dict[str, Any], str]:
    if not cik:
        return {
            "ticker": symbol,
            "sec_status": "NO_CIK",
            "cik": None,
            "latest_form": None,
            "latest_filing_date": None,
            "catalyst_forms": [],
            "risk_flags": [],
            "filings": [],
        }, ""

    try:
        with rate_lock:
            now = time.time()
            elapsed = now - last_time_ref[0]
            if elapsed < 0.11:  # SEC allows 10 requests per second -> 0.1s minimum delay
                time.sleep(0.11 - elapsed)
            last_time_ref[0] = time.time()

        submissions = fetch_company_submissions(cik)
        return summarize_filings(symbol, cik, submissions), ""
    except Exception as exc:
        return {
            "ticker": symbol,
            "sec_status": "ERROR",
            "cik": cik,
            "error": str(exc),
            "latest_form": None,
            "latest_filing_date": None,
            "catalyst_forms": [],
            "risk_flags": [],
            "filings": [],
        }, f"{symbol}: {exc}"

def run_sec_catalyst_scanner() -> Dict[str, Any]:
    generated_at = now_utc_iso()
    errors = []
    rows = []

    symbols = load_symbols(limit=50)

    try:
        ticker_map = load_ticker_map()
    except Exception as exc:
        ticker_map = {}
        errors.append(f"Failed to load SEC ticker map: {exc}")

    rate_lock = threading.Lock()
    last_time_ref = [0.0]

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_symbol = {
            executor.submit(_process_symbol, symbol, ticker_map.get(symbol), rate_lock, last_time_ref): symbol
            for symbol in symbols
        }

        results_by_symbol = {}
        for future in concurrent.futures.as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            try:
                row, err = future.result()
                results_by_symbol[symbol] = (row, err)
            except Exception as exc:
                results_by_symbol[symbol] = ({
                    "ticker": symbol,
                    "sec_status": "ERROR",
                    "cik": ticker_map.get(symbol),
                    "error": str(exc),
                    "latest_form": None,
                    "latest_filing_date": None,
                    "catalyst_forms": [],
                    "risk_flags": [],
                    "filings": [],
                }, f"{symbol}: Exception in thread: {exc}")

    for symbol in symbols:
        if symbol in results_by_symbol:
            row, err = results_by_symbol[symbol]
            rows.append(row)
            if err:
                errors.append(err)

    payload = {
        "schema_version": "sec_catalyst_scanner_v2",
        "generated_at": generated_at,
        "status": "PASS" if not errors else "WARN",
        "symbols_checked": symbols,
        "rows": rows,
        "errors": errors[:20],
        "safety": {
            "paper_only": True,
            "order_submission": False,
            "sec_layer_is_context_only": True,
            "disclaimer": "SEC context only. Not financial advice.",
        },
    }

    health = {
        "schema_version": "sec_catalyst_health_v2",
        "generated_at": generated_at,
        "status": payload["status"],
        "message": "SEC catalyst scan completed" if not errors else "SEC scan completed with warnings",
        "symbols_checked": len(symbols),
        "rows": len(rows),
        "error_count": len(errors),
        "errors": errors[:20],
        "paper_only": True,
        "order_submission": False,
    }

    write_json(OUTPUT_PATH, payload)
    write_json(STATE_PATH, payload)
    write_json(HEALTH_PATH, health)

    return {
        "status": payload["status"],
        "symbols_checked": len(symbols),
        "rows": len(rows),
        "error_count": len(errors),
        "output_path": str(OUTPUT_PATH),
        "health_path": str(HEALTH_PATH),
    }


def main() -> None:
    print(json.dumps(run_sec_catalyst_scanner(), indent=2))


if __name__ == "__main__":
    main()
