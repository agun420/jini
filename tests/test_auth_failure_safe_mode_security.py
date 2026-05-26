import json
from pathlib import Path
from unittest.mock import patch
from scripts.auth_failure_safe_mode import export

def test_auth_safe_mode_bypass_prevention(tmp_path):
    # Setup mock data to simulate when is_auth_failed is false,
    # but a row already has auth_safe_mode=True

    docs_dir = tmp_path / "docs" / "data" / "prediction_engine"
    state_dir = tmp_path / "state" / "prediction_engine"
    docs_dir.mkdir(parents=True)
    state_dir.mkdir(parents=True)

    diagnostic_health_file = docs_dir / "alpaca_source_diagnostic_health.json"
    diagnostic_health_file.write_text(json.dumps({
        "status": "PASS",
        "blockers": [],
        "warnings": [],
        "trading_auth_ok": True,
        "iex_data_ok": True,
        "sip_data_ok": True
    }))

    scanner_stable_file = docs_dir / "signal_dashboard_stable.json"
    scanner_stable_file.write_text(json.dumps({
        "rows": [
            {
                "symbol": "AAPL",
                "auth_safe_mode": True,
                "auth_safe_mode_reason": "previous_failure"
            },
            {
                "symbol": "MSFT",
                "auth_safe_mode": False,
                "auth_safe_mode_reason": "alpaca_auth_ok_or_unknown"
            }
        ]
    }))

    # Patch the paths so the script uses our temp directory
    with patch("scripts.auth_failure_safe_mode.DOCS_DIR", docs_dir), \
         patch("scripts.auth_failure_safe_mode.STATE_DIR", state_dir), \
         patch("scripts.auth_failure_safe_mode.DIAGNOSTIC_HEALTH", diagnostic_health_file), \
         patch("scripts.auth_failure_safe_mode.DIAGNOSTIC_FULL", docs_dir / "alpaca_source_diagnostic.json"), \
         patch("scripts.auth_failure_safe_mode.SCANNER_STABLE", scanner_stable_file), \
         patch("scripts.auth_failure_safe_mode.DATA_GUARD", docs_dir / "signal_dashboard_data_guard_enriched.json"), \
         patch("scripts.auth_failure_safe_mode.RVOL_DASH", docs_dir / "signal_dashboard_rvol_enriched.json"), \
         patch("scripts.auth_failure_safe_mode.OUT_DASHBOARD", docs_dir / "signal_dashboard_safe_mode.json"), \
         patch("scripts.auth_failure_safe_mode.OUT_HEALTH", docs_dir / "auth_failure_safe_mode_health.json"), \
         patch("scripts.auth_failure_safe_mode.OUT_STATE", state_dir / "auth_failure_safe_mode.json"):

        result = export()

        # Check that the overall status is PASS/Safe mode is not globally active
        assert result["safe_mode_active"] is False

        # Read the resulting dashboard file
        out_dashboard = docs_dir / "signal_dashboard_safe_mode.json"
        dashboard_data = json.loads(out_dashboard.read_text())

        rows = dashboard_data["rows"]
        assert len(rows) == 2

        # The first row (AAPL) should STILL have auth_safe_mode == True
        aapl_row = next(r for r in rows if r["symbol"] == "AAPL")
        assert aapl_row["auth_safe_mode"] is True
        assert aapl_row["auth_safe_mode_reason"] == "previous_failure"

        # The second row (MSFT) should be False
        msft_row = next(r for r in rows if r["symbol"] == "MSFT")
        assert msft_row["auth_safe_mode"] is False
