import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from src.prediction_engine.utils import write_json

def test_write_json_success(tmp_path):
    target_path = tmp_path / "nested" / "test.json"
    payload = {"key": "value", "list": [1, 2, 3]}

    write_json(target_path, payload)

    assert target_path.exists()
    assert target_path.parent.exists()

    content = json.loads(target_path.read_text(encoding="utf-8"))
    assert content == payload

def test_write_json_serialization_error(tmp_path):
    target_path = tmp_path / "test.json"
    # A set is not JSON serializable
    payload = {"key": set([1, 2, 3])}

    with pytest.raises(TypeError):
        write_json(target_path, payload)

    assert not target_path.exists()

@patch("pathlib.Path.mkdir")
def test_write_json_mkdir_error(mock_mkdir, tmp_path):
    mock_mkdir.side_effect = PermissionError("Mocked permission error")
    target_path = tmp_path / "test.json"
    payload = {"key": "value"}

    with pytest.raises(PermissionError):
        write_json(target_path, payload)

@patch("pathlib.Path.write_text")
def test_write_json_write_error(mock_write_text, tmp_path):
    mock_write_text.side_effect = OSError("Mocked OS error")
    target_path = tmp_path / "test.json"
    payload = {"key": "value"}

    with pytest.raises(OSError):
        write_json(target_path, payload)
