1. **Understand & Analyze**: Understand the `build_paper_gate_payload` function in `src/prediction_engine/trade_gate/paper_execution_gate.py` which requires mocking for tests.
2. **Create Test File**: Create `tests/test_paper_execution_gate.py` to test payload construction.
3. **Write Tests**:
    - Test the happy path where all functions return successfully and verify the correct structure of the payload.
    - Mock internal dependencies like `load_signal_rows`, `load_guard`, `alpaca_headers`, `fetch_paper_account_snapshot`, `choose_best_candidate`, `create_order_plan`, and `submit_order_if_enabled`.
4. **Pre-commit step**: Complete pre-commit steps to ensure proper testing, verification, review, and reflection are done.
5. **Submit**: Verify tests pass without regression and submit PR.
