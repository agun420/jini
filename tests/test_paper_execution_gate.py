from __future__ import annotations

import json
from unittest.mock import patch

from prediction_engine.trade_gate.paper_execution_gate import main


@patch("sys.argv", ["paper_execution_gate.py"])
@patch("prediction_engine.trade_gate.paper_execution_gate.write_json")
@patch("prediction_engine.trade_gate.paper_execution_gate.build_paper_gate_payload")
def test_main_cli_entry_point(mock_build_payload, mock_write_json, capsys):
    mock_build_payload.return_value = {
        "generated_at": "2023-01-01T00:00:00Z",
        "status": "PASS",
        "order_plan": {"created": True},
        "submission": {"submitted": False},
        "selected_candidate": {"ticker": "AAPL"},
        "adaptive_guard": {"risk_mode": "NORMAL", "allow_new_entries": True},
        "account_snapshot": {"available": True},
        "signal_source": "test_source",
    }

    main()

    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert output["status"] == "PASS"
    assert output["order_plan_created"] is True
    assert output["order_submitted"] is False
    assert output["selected_ticker"] == "AAPL"

    assert mock_write_json.call_count == 3
