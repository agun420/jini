from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from src.prediction_engine.trade_gate.paper_execution_gate import read_json


def test_read_json_file_not_exists(tmp_path):
    file_path = tmp_path / "nonexistent.json"
    default_val = {"default": "value"}
    result = read_json(file_path, default_val)
    assert result == default_val


def test_read_json_valid_json(tmp_path):
    file_path = tmp_path / "valid.json"
    data = {"key": "value", "number": 42}
    file_path.write_text(json.dumps(data), encoding="utf-8")

    result = read_json(file_path, {})
    assert result == data


def test_read_json_invalid_json(tmp_path):
    file_path = tmp_path / "invalid.json"
    file_path.write_text("{invalid_json: 42", encoding="utf-8")

    default_val = {"default": "value"}
    result = read_json(file_path, default_val)
    assert result == default_val


def test_read_json_empty_file(tmp_path):
    file_path = tmp_path / "empty.json"
    file_path.write_text("   \n  \t ", encoding="utf-8")

    default_val = {"default": "value"}
    result = read_json(file_path, default_val)
    assert result == default_val


def test_read_json_exception_during_read(tmp_path):
    file_path = tmp_path / "valid.json"
    file_path.write_text('{"key": "value"}', encoding="utf-8")

    default_val = {"default": "value"}

    # Mock read_text to throw an exception
    with patch.object(Path, "read_text", side_effect=PermissionError("Permission denied")):
        result = read_json(file_path, default_val)

    assert result == default_val
