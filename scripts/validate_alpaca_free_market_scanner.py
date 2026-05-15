from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    required = [
        "state/prediction_engine/dynamic_alpaca_candidates.json",
        "docs/data/prediction_engine/alpaca_market_scanner_health.json",
    ]

    for item in required:
        path = Path(item)
        if not path.exists():
            raise SystemExit(f"Missing required output: {item}")
        json.loads(path.read_text(encoding="utf-8"))

    payload = json.loads(Path("state/prediction_engine/dynamic_alpaca_candidates.json").read_text())
    rows = payload.get("rows", [])

    if not isinstance(rows, list):
        raise SystemExit("dynamic_alpaca_candidates.json rows must be a list")

    print("Alpaca candidates status:", payload.get("status"))
    print("Alpaca candidate rows:", len(rows))

    if rows:
        first = rows[0]
        for key in ["ticker", "price", "source_type", "candidate_quality"]:
            if key not in first:
                raise SystemExit(f"First candidate missing key: {key}")

    print("Alpaca free market scanner validation passed.")


if __name__ == "__main__":
    main()
