from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HEALTH_PATH = Path("docs/data/prediction_engine/sec_catalyst_health.json")


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
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    payload = read_json(HEALTH_PATH, {})

    if not payload:
        payload = {
            "schema_version": "sec_catalyst_health_v2",
            "generated_at": now_utc_iso(),
            "status": "WARN",
            "message": "SEC catalyst health file was missing. SEC layer may not have run yet.",
            "paper_only": True,
            "order_submission": False,
        }
    else:
        payload.setdefault("schema_version", "sec_catalyst_health_v2")
        payload.setdefault("generated_at", now_utc_iso())
        payload.setdefault("paper_only", True)
        payload.setdefault("order_submission", False)

        if payload.get("status") == "WARN" and not payload.get("message"):
            payload["message"] = (
                "SEC catalyst layer returned WARN. Check SEC_USER_AGENT, request limits, "
                "or whether no recent filings were found."
            )

    write_json(HEALTH_PATH, payload)

    print(json.dumps({
        "status": "PASS",
        "message": "SEC health file normalized.",
        "health_path": str(HEALTH_PATH),
        "sec_status": payload.get("status"),
        "sec_message": payload.get("message"),
    }, indent=2))


if __name__ == "__main__":
    main()
