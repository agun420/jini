from __future__ import annotations

import json
from unittest.mock import patch

from prediction_engine.trade_gate.paper_execution_gate import load_signal_rows


def test_load_signal_rows_empty(tmp_path):
    """When all candidate files are missing or empty, it should return [], 'none'."""
    missing_file = tmp_path / "missing.json"
    with patch("prediction_engine.trade_gate.paper_execution_gate.SIGNAL_CANDIDATES", [missing_file]):
        rows, path = load_signal_rows()
        assert rows == []
        assert path == "none"


def test_load_signal_rows_first_valid(tmp_path, minimal_row):
    """When the first candidate file has valid rows, it should return them and its path."""
    file1 = tmp_path / "file1.json"
    file2 = tmp_path / "file2.json"

    file1.write_text(json.dumps([minimal_row]))
    file2.write_text(json.dumps([{"ticker": "OTHER"}]))

    with patch("prediction_engine.trade_gate.paper_execution_gate.SIGNAL_CANDIDATES", [file1, file2]):
        rows, path = load_signal_rows()
        assert len(rows) == 1
        assert rows[0] == minimal_row
        assert path == str(file1)


def test_load_signal_rows_fallback(tmp_path, minimal_row):
    """When the first file is missing, but the second file has valid rows, it should fallback to the second."""
    file1 = tmp_path / "missing.json"
    file2 = tmp_path / "file2.json"

    file2.write_text(json.dumps([minimal_row]))

    with patch("prediction_engine.trade_gate.paper_execution_gate.SIGNAL_CANDIDATES", [file1, file2]):
        rows, path = load_signal_rows()
        assert len(rows) == 1
        assert rows[0] == minimal_row
        assert path == str(file2)


def test_load_signal_rows_malformed_json(tmp_path, minimal_row):
    """When a file exists but contains malformed JSON, it should skip it and try the next."""
    file1 = tmp_path / "file1.json"
    file2 = tmp_path / "file2.json"

    file1.write_text("invalid json {")
    file2.write_text(json.dumps([minimal_row]))

    with patch("prediction_engine.trade_gate.paper_execution_gate.SIGNAL_CANDIDATES", [file1, file2]):
        rows, path = load_signal_rows()
        assert len(rows) == 1
        assert rows[0] == minimal_row
        assert path == str(file2)


def test_load_signal_rows_empty_list(tmp_path, minimal_row):
    """When a file exists but contains no rows, it should skip it and try the next."""
    file1 = tmp_path / "file1.json"
    file2 = tmp_path / "file2.json"

    file1.write_text(json.dumps([]))
    file2.write_text(json.dumps([minimal_row]))

    with patch("prediction_engine.trade_gate.paper_execution_gate.SIGNAL_CANDIDATES", [file1, file2]):
        rows, path = load_signal_rows()
        assert len(rows) == 1
        assert rows[0] == minimal_row
        assert path == str(file2)
