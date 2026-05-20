from __future__ import annotations

import json
from pathlib import Path

from prediction_engine.learning.trade_journal import TradeJournal


DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

STATE_PATH = STATE / "trade_journal.json"
DOCS_HEALTH = DOCS / "trade_journal_health.json"
DOCS_SNAPSHOT = DOCS / "trade_journal_snapshot.json"


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    journal = TradeJournal(STATE_PATH)
    health = journal.health()

    snapshot = {
        "schema_version": "trade_journal_snapshot_v1",
        "health": health,
        "records": journal.list_records()[-100:],
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
        },
    }

    write_json(DOCS_HEALTH, health)
    write_json(DOCS_SNAPSHOT, snapshot)

    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    main()
