from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

SIGNAL_DASHBOARD_PATH = Path("docs/data/prediction_engine/signal_dashboard.json")
FREE_SCANNER_PATH = Path("docs/data/prediction_engine/free_scanner.json")
SEC_PATH = Path("docs/data/prediction_engine/sec_catalysts.json")
ENRICHED_SIGNAL_PATH = Path("docs/data/prediction_engine/signal_dashboard_enriched.json")
ENRICHED_SCANNER_PATH = Path("docs/data/prediction_engine/free_scanner_enriched.json")


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


def sec_map() -> Dict[str, Dict[str, Any]]:
    payload = read_json(SEC_PATH, {})
    rows = payload.get("rows") if isinstance(payload, dict) else []
    out = {}
    for row in rows if isinstance(rows, list) else []:
        ticker = str(row.get("ticker") or "").upper().strip()
        if ticker:
            out[ticker] = row
    return out


def apply_sec_fields(row: Dict[str, Any], sec: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
    sec_row = sec.get(ticker, {})
    if not sec_row:
        row["sec_catalyst"] = {
            "final_label": "NOT_CHECKED",
            "catalyst_score": 0,
            "filing_risk_score": 0,
            "risk_flags": [],
            "catalyst_flags": [],
        }
        return row

    row["sec_catalyst"] = {
        "final_label": sec_row.get("final_label"),
        "catalyst_score": sec_row.get("catalyst_score", 0),
        "filing_risk_score": sec_row.get("filing_risk_score", 0),
        "latest_filings": sec_row.get("latest_filings", [])[:3],
        "risk_flags": sec_row.get("risk_flags", []),
        "catalyst_flags": sec_row.get("catalyst_flags", []),
    }

    # Conservative enrichment only. Do not create new TRADE_ELIGIBLE signals here.
    if sec_row.get("final_label") == "DILUTION_OR_FILING_RISK":
        reasons = row.get("no_trade_reasons") if isinstance(row.get("no_trade_reasons"), list) else []
        if "sec_dilution_or_filing_risk" not in reasons:
            reasons.append("sec_dilution_or_filing_risk")
        row["no_trade_reasons"] = reasons
        row["status_before_sec"] = row.get("status")
        row["status"] = "NO_TRADE"
        row["signal"] = "NO TRADE"
        row["action"] = "No new entry. SEC filing risk detected."
        try:
            row["score"] = max(0, float(row.get("score") or 0) - 15)
        except Exception:
            row["score"] = 0
    elif sec_row.get("final_label") == "POSSIBLE_CATALYST":
        row["sec_note"] = "Possible SEC catalyst found. Confirmation still required."
        # Small informational boost only if existing score exists. This does not bypass status gates.
        try:
            row["score_before_sec"] = float(row.get("score") or 0)
            row["score"] = min(100, row["score_before_sec"] + 5)
        except Exception:
            pass

    return row


def enrich_payload(input_path: Path, output_path: Path, sec: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    payload = read_json(input_path, {})
    if not isinstance(payload, dict):
        payload = {}
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    enriched_rows = [apply_sec_fields(dict(row), sec) for row in rows if isinstance(row, dict)]
    payload["rows"] = enriched_rows
    payload["sec_enriched_at"] = datetime.now(timezone.utc).isoformat()
    payload["sec_enrichment"] = {
        "enabled": True,
        "source": str(SEC_PATH),
        "rule": "SEC can penalize/block risky filings and provide catalyst context, but cannot trigger buys by itself.",
    }
    write_json(output_path, payload)
    return payload


def main() -> None:
    sec = sec_map()
    signal = enrich_payload(SIGNAL_DASHBOARD_PATH, ENRICHED_SIGNAL_PATH, sec)
    scanner = enrich_payload(FREE_SCANNER_PATH, ENRICHED_SCANNER_PATH, sec)
    print(json.dumps({
        "status": "PASS",
        "sec_rows": len(sec),
        "signal_rows": len(signal.get("rows", [])),
        "scanner_rows": len(scanner.get("rows", [])),
        "outputs": [str(ENRICHED_SIGNAL_PATH), str(ENRICHED_SCANNER_PATH)],
    }, indent=2))


if __name__ == "__main__":
    main()
