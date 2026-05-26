from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from prediction_engine.trade_gate.paper_execution_gate import now_utc_iso


def test_now_utc_iso():
    """Test that now_utc_iso returns a valid ISO formatted string in UTC."""
    result = now_utc_iso()

    # Check that it's a string
    assert isinstance(result, str)

    # Parse the ISO string back into a datetime object
    try:
        parsed_dt = datetime.fromisoformat(result)
    except ValueError:
        assert False, f"Returned string '{result}' is not a valid ISO format"

    # Check that it is in UTC
    assert parsed_dt.tzinfo == timezone.utc

    # Check that it represents the current time (within a reasonable margin, e.g., 5 seconds)
    now = datetime.now(timezone.utc)
    assert abs(now - parsed_dt) < timedelta(seconds=5)
