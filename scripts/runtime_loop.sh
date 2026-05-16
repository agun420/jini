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
export RUNTIME_LOOP_FOREVER="true"
export RUNTIME_INTERVAL_SECONDS="${RUNTIME_INTERVAL_SECONDS:-60}"

python -m prediction_engine.runtime.runtime_worker
