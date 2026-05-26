import json
from unittest.mock import patch

from prediction_engine.trade_gate.paper_execution_gate import main


@patch("prediction_engine.trade_gate.paper_execution_gate.export_paper_gate")
@patch("builtins.print")
def test_main(mock_print, mock_export):
    dummy_response = {"status": "PASS", "order_plan_created": True}
    mock_export.return_value = dummy_response

    main()

    mock_export.assert_called_once()
    mock_print.assert_called_once_with(json.dumps(dummy_response, indent=2))
