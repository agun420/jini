import pytest
from prediction_engine.trade_gate.paper_execution_gate import safe_float

@pytest.mark.parametrize(
    "value, default, expected",
    [
        (1, None, 1.0),
        (1.5, None, 1.5),
        ("2.5", None, 2.5),
        ("-3.14", None, -3.14),
        ("0", None, 0.0),
        (None, None, None),
        (None, 42.0, 42.0),
        ("", None, None),
        ("", 42.0, 42.0),
        ("abc", None, None),
        ("abc", 42.0, 42.0),
        ("  ", None, None),
        ("  ", 42.0, 42.0),
        ([], None, None),
        ({}, 42.0, 42.0),
        (object(), None, None),
    ],
)
def test_safe_float(value, default, expected):
    """Test safe_float handles valid, missing, empty, and invalid inputs."""
    assert safe_float(value, default) == expected
