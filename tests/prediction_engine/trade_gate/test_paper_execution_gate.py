import pytest
from prediction_engine.trade_gate.paper_execution_gate import safe_float


@pytest.mark.parametrize(
    "value, default, expected",
    [
        (10.5, None, 10.5),
        ("10.5", 0.0, 10.5),
        (10, None, 10.0),
        (None, 5.0, 5.0),
        (None, None, None),
        ("", 2.0, 2.0),
        ("", None, None),
        ("invalid", -1.0, -1.0),
        ("invalid", None, None),
    ],
)
def test_safe_float(value, default, expected):
    assert safe_float(value, default) == expected
