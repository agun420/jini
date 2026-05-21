#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
fi

if [ -f "scripts/load_env.sh" ]; then
  source scripts/load_env.sh
elif [ -f ".env" ]; then
  set -a
  source .env
  set +a
fi

export PYTHONPATH="${PYTHONPATH:-src:.}"
export PAPER_ORDER_SUBMISSION_ENABLED="${PAPER_ORDER_SUBMISSION_ENABLED:-false}"
export MANUAL_APPROVAL_REQUIRED="${MANUAL_APPROVAL_REQUIRED:-true}"
export ENGINE_KILL_SWITCH="${ENGINE_KILL_SWITCH:-false}"

INTERVAL="${RUNTIME_INTERVAL_SECONDS:-300}"

run_once() {
  echo "=== Jini runtime tick: $(date -u) ==="

  git fetch origin || true
  git reset --hard origin/main || true

  PYTHONPATH=src:. python scripts/run_runtime_worker.py || true
  PYTHONPATH=src:. python scripts/run_scanner_data_source_stabilizer.py || true
  PYTHONPATH=src:. python scripts/run_three_score_matrix.py || true
  PYTHONPATH=src:. python scripts/run_second_leg_fsm.py || true
  PYTHONPATH=src:. python scripts/run_time_slot_rvol.py || true
  PYTHONPATH=src:. python scripts/run_data_feed_truth_guard.py || true
  PYTHONPATH=src:. python scripts/run_walk_forward_test.py || true
  PYTHONPATH=src:. python scripts/run_meta_labeling.py || true
  PYTHONPATH=src:. python scripts/run_production_monitor.py || true
  PYTHONPATH=src:. python scripts/run_alert_delivery.py || true
  PYTHONPATH=src:. python scripts/run_alpaca_source_diagnostic.py || true
  PYTHONPATH=src:. python scripts/run_auth_failure_safe_mode.py || true
  PYTHONPATH=src:. python scripts/run_operator_signal_resolver.py || true
  PYTHONPATH=src:. python scripts/run_jini_operator_pipeline.py || true
  PYTHONPATH=src:. python scripts/run_feed_status_quality.py || true
  PYTHONPATH=src:. python scripts/run_v3_prebreakout_predictor.py || true
  PYTHONPATH=src:. python scripts/run_v3_signal_pipeline.py || true
  PYTHONPATH=src:. python scripts/run_v3_research_alert_score.py || true
  PYTHONPATH=src:. python scripts/run_v3_research_alert_outcome_journal.py || true
  PYTHONPATH=src:. python scripts/run_buy_order_alert_outcome_journal.py || true
  PYTHONPATH=src:. python scripts/run_validation_core_manifest.py || true
  PYTHONPATH=src:. python scripts/run_trade_journal_health.py || true
  PYTHONPATH=src:. python scripts/run_blocked_journal_health.py || true
  PYTHONPATH=src:. python scripts/run_slippage_quality_audit.py || true
  PYTHONPATH=src:. python scripts/run_forward_validation_optimizer.py || true
  PYTHONPATH=src:. python scripts/run_validation_status_aggregator.py || true
  PYTHONPATH=src:. python scripts/run_auto_trade_readiness_audit.py || true
  PYTHONPATH=src:. python scripts/run_final_repo_audit.py || true
  PYTHONPATH=src:. python scripts/run_backtest_gate.py || true
  PYTHONPATH=src:. python scripts/run_jini_stability_check.py || true

  git add docs/data/prediction_engine state/prediction_engine || true
  git commit -m "Update Jini VM dashboard data" || true
  git pull --rebase origin main || true
  git push origin main || true
}

if [ "${RUNTIME_LOOP_FOREVER:-true}" = "false" ]; then
  run_once
  exit 0
fi

while true; do
  run_once
  sleep "${INTERVAL}"
done
