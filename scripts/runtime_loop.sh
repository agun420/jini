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
  PYTHONPATH=src:. python scripts/run_three_score_matrix.py || true
  PYTHONPATH=src:. python scripts/run_second_leg_fsm.py || true
  PYTHONPATH=src:. python scripts/run_time_slot_rvol.py || true
  PYTHONPATH=src:. python scripts/run_walk_forward_test.py || true
  PYTHONPATH=src:. python scripts/run_meta_labeling.py || true
  PYTHONPATH=src:. python scripts/run_production_monitor.py || true
  PYTHONPATH=src:. python scripts/run_alert_delivery.py || true
  PYTHONPATH=src:. python scripts/run_final_repo_audit.py || true

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
