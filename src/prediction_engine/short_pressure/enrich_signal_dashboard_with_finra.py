from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

SHORT_PRESSURE_PATH = Path("docs/data/prediction_engine/finra_short_pressure.json")
SIGNAL_INPUT_CANDIDATES = [
    Path("docs/data/prediction_engine/signal_dashboard_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard.json"),
]
FREE_INPUT_CANDIDATES = [
    Path("docs/data/prediction_engine/free_scanner_enriched.json"),
    Path("docs/data/prediction_engine/free_scanner.json"),
]

SIGNAL_OUTPUT_PATH = Path("docs/data/prediction_engine/signal_dashboard_finra_enriched.json")
FREE_OUTPUT_PATH = Path("docs/data/prediction_engine/free_scanner_finra_enriched.json")


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


def first_existing(paths: List[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def index_pressure() -> Dict[str, Dict[str, Any]]:
    payload = read_json(SHORT_PRESSURE_PATH, {})
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").upper().strip()
        if ticker:
            out[ticker] = row
    return out


def enrich_rows(rows: List[Dict[str, Any]], pressure_by_ticker: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for row in rows:
        item = deepcopy(row)
        ticker = str(item.get("ticker") or item.get("symbol") or "").upper().strip()
        pressure = pressure_by_ticker.get(ticker)
        if pressure:
            item["finra_short_pressure"] = pressure
            item["short_pressure_score"] = pressure.get("short_pressure_score")
            item["short_pressure_label"] = pressure.get("short_pressure_label")
            item["short_volume_ratio"] = pressure.get("short_volume_ratio")
            notes = list(item.get("enrichment_notes") or [])
            notes.append("FINRA short-pressure context attached. Context only, not a buy trigger.")
            item["enrichment_notes"] = notes
        else:
            item["finra_short_pressure"] = {
                "ticker": ticker,
                "short_pressure_label": "NO_DATA",
                "short_pressure_score": 0,
                "notes": ["no_finra_context_found"],
            }
            item["short_pressure_score"] = 0
            item["short_pressure_label"] = "NO_DATA"
        enriched.append(item)
    return enriched


def enrich_payload(input_paths: List[Path], output_path: Path, payload_type: str) -> Dict[str, Any]:
    pressure_by_ticker = index_pressure()
    source_path = first_existing(input_paths)

    if source_path is None:
        payload = {
            "schema_version": f"{payload_type}_finra_enriched_v1",
            "generated_at": now_utc_iso(),
            "status": "NO_INPUT",
            "rows": [],
            "notes": ["No input dashboard/scanner file found to enrich."],
        }
        write_json(output_path, payload)
        return payload

    payload = read_json(source_path, {})
    if not isinstance(payload, dict):
        payload = {}

    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    enriched_rows = enrich_rows(rows, pressure_by_ticker)

    output = deepcopy(payload)
    output["schema_version"] = f"{payload.get('schema_version', payload_type)}_finra_enriched_v1"
    output["generated_at"] = now_utc_iso()
    output["source_file"] = str(source_path)
    output["rows"] = enriched_rows
    output["finra_enrichment"] = {
        "status": "PASS",
        "source_file": str(SHORT_PRESSURE_PATH),
        "rows_enriched": len(enriched_rows),
        "matched_finra_rows": sum(1 for r in enriched_rows if r.get("short_pressure_label") not in {None, "NO_DATA"}),
        "context_only": True,
        "order_submission": False,
    }

    write_json(output_path, output)
    return output


def export_enriched() -> Dict[str, Any]:
    signal_payload = enrich_payload(SIGNAL_INPUT_CANDIDATES, SIGNAL_OUTPUT_PATH, "signal_dashboard")
    free_payload = enrich_payload(FREE_INPUT_CANDIDATES, FREE_OUTPUT_PATH, "free_scanner")

    return {
        "status": "PASS",
        "signal_output_path": str(SIGNAL_OUTPUT_PATH),
        "free_output_path": str(FREE_OUTPUT_PATH),
        "signal_rows": len(signal_payload.get("rows", [])),
        "free_rows": len(free_payload.get("rows", [])),
    }


def main() -> None:
    print(json.dumps(export_enriched(), indent=2))


if __name__ == "__main__":
    main()
