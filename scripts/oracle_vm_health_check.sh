#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== Jini Oracle VM Health Check ==="
echo "Repo: $(pwd)"
echo

echo "Python:"
python3 --version || python --version
echo

echo "Git:"
git status --short || true
echo

echo "Environment check:"
PYTHONPATH=src:. python3 scripts/oracle_vm_env_check.py || PYTHONPATH=src:. python scripts/oracle_vm_env_check.py
echo

echo "Runtime worker one-loop check:"
PYTHONPATH=src:. RUNTIME_LOOP_FOREVER=false python3 scripts/run_runtime_worker.py || PYTHONPATH=src:. RUNTIME_LOOP_FOREVER=false python scripts/run_runtime_worker.py
echo

echo "Final repo audit:"
PYTHONPATH=src:. python3 scripts/run_final_repo_audit.py || PYTHONPATH=src:. python scripts/run_final_repo_audit.py
echo

echo "Service status:"
if command -v systemctl >/dev/null 2>&1; then
  systemctl status jini-runtime --no-pager || true
  systemctl status jini-dashboard --no-pager || true
else
  echo "systemctl not available in this environment."
fi
echo

echo "Dashboard port:"
if command -v ss >/dev/null 2>&1; then
  ss -ltnp | grep ':8000' || echo "Port 8000 is not listening."
else
  echo "ss command not available."
fi

echo
echo "Health check completed."
