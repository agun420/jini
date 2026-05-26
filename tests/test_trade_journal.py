import pytest
import os
import json
from pathlib import Path
from prediction_engine.learning.trade_journal import TradeJournal, OpenTradeRequest

def test_trade_journal_open_close_trade(tmp_path):
    journal_path = tmp_path / "trade_journal.json"
    journal = TradeJournal(storage_path=journal_path)

    req = OpenTradeRequest(
        ticker="AAPL",
        entry_signal_price=150.0,
        execution_layers=[{"name": "signal_fill", "weight": 1.0, "fill": 150.5}],
        atr=2.5,
        vwap_dist=0.5,
        score=0.85,
        regime="BULL",
        shares=100
    )

    trade_id = journal.open_trade(req)

    assert trade_id is not None
    assert trade_id.startswith("AAPL_")

    records = journal.list_records()
    assert len(records) == 1
    assert records[0]["status"] == "OPEN"
    assert records[0]["ticker"] == "AAPL"

    journal.close_trade(trade_id, exit_fill=160.0)

    records_after = journal.list_records()
    assert records_after[0]["status"] == "CLOSED"
    assert records_after[0]["outcome_pnl"] == (160.0 - 150.5) * 100
