from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

CANDIDATE_INPUTS = [
    Path("docs/data/prediction_engine/free_scanner.json"),
    Path("docs/data/prediction_engine/signal_dashboard.json"),
    Path("state/prediction_engine/dynamic_alpaca_candidates.json"),
    Path("state/prediction_engine/dynamic_discovery_candidates.json"),
]

OUTPUT_PATH = Path("docs/data/prediction_engine/sec_catalysts.json")
HEALTH_PATH = Path("docs/data/prediction_engine/sec_catalyst_health.json")
CACHE_PATH = Path("state/prediction_engine/sec_catalyst_cache.json")

SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

DEFAULT_USER_AGENT = "engine1v2-free-scanner/1.0 contact@example.com"

BULLISH_FORMS = {"8-K", "6-K", "10-Q", "10-K", "SC 13D", "SC 13G", "4"}
RISK_FORMS = {"S-1", "S-3", "424B", "424B3", "424B5", "EFFECT", "RW", "DEF 14A", "PRE 14A"}

BULLISH_KEYWORDS = [
    "agreement",
    "contract",
    "partnership",
    "collaboration",
    "approval",
    "fda",
    "merger",
    "acquisition",
    "earnings",
    "guidance",
    "award",
    "strategic",
    "commercial",
    "license",
]

RISK_KEYWORDS = [
    "offering",
    "shelf",
    "atm",
    "at-the-market",
    "dilution",
    "warrant",
    "convertible",
    "reverse split",
    "going concern",
    "delisting",
    "resale",
]


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


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=False), encoding="utf-8")


def normalize_symbol(value: Any) -> str:
    return str(value or "").upper().strip()


def extract_rows(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "candidates", "predictions", "signals", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def extract_symbols() -> List[str]:
    symbols: List[str] = []
    for path in CANDIDATE_INPUTS:
        payload = read_json(path, None)
        for row in extract_rows(payload):
            symbol = normalize_symbol(row.get("ticker") or row.get("symbol") or row.get("S") or row.get("T"))
            if symbol:
                symbols.append(symbol)
    # Keep order, dedupe, cap for free/SEC courtesy.
    seen = set()
    out = []
    for symbol in symbols:
        if symbol not in seen:
            seen.add(symbol)
            out.append(symbol)
    return out[:50]


def request_json(url: str, timeout: int = 20) -> Any:
    user_agent = os.getenv("SEC_USER_AGENT", DEFAULT_USER_AGENT)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Host": "www.sec.gov" if "www.sec.gov" in url else "data.sec.gov",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read()
    return json.loads(body.decode("utf-8"))


def load_ticker_cik_map() -> Dict[str, str]:
    cache = read_json(CACHE_PATH, {})
    cached_map = cache.get("ticker_cik_map") if isinstance(cache, dict) else None
    cached_at = cache.get("ticker_cik_map_cached_at") if isinstance(cache, dict) else None
    if isinstance(cached_map, dict) and cached_map:
        return {normalize_symbol(k): str(v).zfill(10) for k, v in cached_map.items()}

    raw = request_json(SEC_COMPANY_TICKERS_URL)
    ticker_map: Dict[str, str] = {}
    if isinstance(raw, dict):
        for item in raw.values():
            if not isinstance(item, dict):
                continue
            ticker = normalize_symbol(item.get("ticker"))
            cik = item.get("cik_str")
            if ticker and cik is not None:
                ticker_map[ticker] = str(cik).zfill(10)

    cache = cache if isinstance(cache, dict) else {}
    cache["ticker_cik_map"] = ticker_map
    cache["ticker_cik_map_cached_at"] = now_utc_iso()
    write_json(CACHE_PATH, cache)
    return ticker_map


def latest_filings_for_cik(cik: str, limit: int = 8) -> List[Dict[str, Any]]:
    url = SEC_SUBMISSIONS_URL.format(cik=str(cik).zfill(10))
    raw = request_json(url)
    recent = (((raw or {}).get("filings") or {}).get("recent") or {}) if isinstance(raw, dict) else {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accessions = recent.get("accessionNumber") or []
    primary_docs = recent.get("primaryDocument") or []
    items = recent.get("items") or []

    filings: List[Dict[str, Any]] = []
    for idx, form in enumerate(forms[:limit]):
        filings.append(
            {
                "form": str(form),
                "filing_date": dates[idx] if idx < len(dates) else None,
                "accession_number": accessions[idx] if idx < len(accessions) else None,
                "primary_document": primary_docs[idx] if idx < len(primary_docs) else None,
                "items": items[idx] if idx < len(items) else None,
            }
        )
    return filings


def score_filings(filings: List[Dict[str, Any]]) -> Dict[str, Any]:
    catalyst_score = 0
    risk_score = 0
    catalyst_flags: List[str] = []
    risk_flags: List[str] = []

    for filing in filings:
        form = str(filing.get("form") or "").upper()
        items_text = str(filing.get("items") or "").lower()
        primary_doc = str(filing.get("primary_document") or "").lower()
        combined = f"{form.lower()} {items_text} {primary_doc}"

        if form in BULLISH_FORMS:
            catalyst_score += 8
            catalyst_flags.append(f"recent_{form}")
        if form in RISK_FORMS or form.startswith("S-") or form.startswith("424B"):
            risk_score += 20
            risk_flags.append(f"risk_form_{form}")

        for keyword in BULLISH_KEYWORDS:
            if keyword in combined:
                catalyst_score += 5
                catalyst_flags.append(f"keyword_{keyword}")

        for keyword in RISK_KEYWORDS:
            if keyword in combined:
                risk_score += 8
                risk_flags.append(f"risk_keyword_{keyword}")

    catalyst_score = max(0, min(100, catalyst_score))
    risk_score = max(0, min(100, risk_score))

    if risk_score >= 40:
        final_label = "DILUTION_OR_FILING_RISK"
    elif catalyst_score >= 35:
        final_label = "POSSIBLE_CATALYST"
    elif catalyst_score > 0:
        final_label = "FILING_ACTIVITY"
    else:
        final_label = "NO_RECENT_CATALYST_FOUND"

    return {
        "catalyst_score": catalyst_score,
        "filing_risk_score": risk_score,
        "final_label": final_label,
        "catalyst_flags": sorted(set(catalyst_flags))[:20],
        "risk_flags": sorted(set(risk_flags))[:20],
    }


def scan_sec_catalysts(symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    symbols = symbols or extract_symbols()
    started_at = now_utc_iso()
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []

    if not symbols:
        payload = {
            "schema_version": "sec_catalysts_v1",
            "generated_at": started_at,
            "status": "PASS",
            "rows": [],
            "counts": {"symbols_checked": 0, "with_filings": 0, "possible_catalysts": 0, "filing_risks": 0},
            "notes": ["No symbols found from scanner candidate files."],
            "safety": {"paper_only": True, "order_submission": False, "buy_trigger": False},
        }
        write_json(OUTPUT_PATH, payload)
        write_json(HEALTH_PATH, {"generated_at": started_at, "status": "PASS", "errors": []})
        return payload

    try:
        ticker_map = load_ticker_cik_map()
    except Exception as exc:
        msg = f"Failed to load SEC ticker map: {exc}"
        errors.append(msg)
        payload = {
            "schema_version": "sec_catalysts_v1",
            "generated_at": started_at,
            "status": "WARN",
            "rows": [],
            "counts": {"symbols_checked": len(symbols), "with_filings": 0, "possible_catalysts": 0, "filing_risks": 0},
            "errors": errors,
            "safety": {"paper_only": True, "order_submission": False, "buy_trigger": False},
        }
        write_json(OUTPUT_PATH, payload)
        write_json(HEALTH_PATH, {"generated_at": started_at, "status": "WARN", "errors": errors})
        return payload

    for idx, symbol in enumerate(symbols):
        cik = ticker_map.get(symbol)
        if not cik:
            rows.append(
                {
                    "ticker": symbol,
                    "cik": None,
                    "status": "NO_CIK_FOUND",
                    "latest_filings": [],
                    "catalyst_score": 0,
                    "filing_risk_score": 0,
                    "final_label": "NO_SEC_MATCH",
                    "catalyst_flags": [],
                    "risk_flags": ["no_cik_found"],
                }
            )
            continue

        try:
            filings = latest_filings_for_cik(cik)
            scored = score_filings(filings)
            rows.append(
                {
                    "ticker": symbol,
                    "cik": cik,
                    "status": "PASS",
                    "latest_filings": filings,
                    **scored,
                }
            )
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
            rows.append(
                {
                    "ticker": symbol,
                    "cik": cik,
                    "status": "ERROR",
                    "latest_filings": [],
                    "catalyst_score": 0,
                    "filing_risk_score": 0,
                    "final_label": "SEC_LOOKUP_ERROR",
                    "catalyst_flags": [],
                    "risk_flags": ["sec_lookup_error"],
                    "error": str(exc),
                }
            )
        # SEC-friendly pacing.
        time.sleep(0.12)

    counts = {
        "symbols_checked": len(symbols),
        "with_filings": sum(1 for r in rows if r.get("latest_filings")),
        "possible_catalysts": sum(1 for r in rows if r.get("final_label") == "POSSIBLE_CATALYST"),
        "filing_risks": sum(1 for r in rows if r.get("final_label") == "DILUTION_OR_FILING_RISK"),
        "errors": len(errors),
    }

    payload = {
        "schema_version": "sec_catalysts_v1",
        "generated_at": now_utc_iso(),
        "status": "PASS" if not errors else "WARN",
        "rows": rows,
        "counts": counts,
        "errors": errors[:20],
        "method": {
            "description": "Free SEC EDGAR catalyst/risk tagger.",
            "buy_rule": "SEC data can boost or penalize a scanner score, but cannot trigger a buy by itself.",
            "risk_rule": "Offering, shelf, 424B, reverse split, delisting, or dilution flags should block or penalize trades.",
        },
        "safety": {"paper_only": True, "order_submission": False, "buy_trigger": False},
    }

    health = {
        "schema_version": "sec_catalyst_health_v1",
        "generated_at": payload["generated_at"],
        "status": payload["status"],
        "symbols_checked": counts["symbols_checked"],
        "possible_catalysts": counts["possible_catalysts"],
        "filing_risks": counts["filing_risks"],
        "errors": errors[:20],
        "paper_only": True,
        "order_submission": False,
    }

    write_json(OUTPUT_PATH, payload)
    write_json(HEALTH_PATH, health)
    return payload


def main() -> None:
    payload = scan_sec_catalysts()
    print(json.dumps({"status": payload.get("status"), "counts": payload.get("counts"), "output": str(OUTPUT_PATH)}, indent=2))


if __name__ == "__main__":
    main()
