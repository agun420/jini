from __future__ import annotations

import re
from datetime import datetime, timezone
from unittest.mock import patch

from src.prediction_engine.trade_gate.paper_execution_gate import now_utc_iso


def test_now_utc_iso_format() -> None:
    result = now_utc_iso()
    # Expecting ISO 8601 format like '2023-10-27T10:00:00+00:00'
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(\+00:00|Z)$", result) is not None


@patch("src.prediction_engine.trade_gate.paper_execution_gate.datetime")
def test_now_utc_iso_mocked(mock_datetime) -> None:
    mock_now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    mock_datetime.now.return_value = mock_now

    result = now_utc_iso()

    mock_datetime.now.assert_called_once_with(timezone.utc)
    assert result == "2025-01-01T12:00:00+00:00"
