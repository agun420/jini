#!/usr/bin/env bash
set -euo pipefail

echo "=== Jini Service Status ==="

if command -v systemctl >/dev/null 2>&1; then
  echo
  echo "jini-runtime:"
  systemctl status jini-runtime --no-pager || true

  echo
  echo "jini-dashboard:"
  systemctl status jini-dashboard --no-pager || true
else
  echo "systemctl is not available."
fi

echo
echo "Recent runtime logs:"
if command -v journalctl >/dev/null 2>&1; then
  journalctl -u jini-runtime -n 60 --no-pager || true
else
  echo "journalctl is not available."
fi

echo
echo "Port 8000:"
if command -v ss >/dev/null 2>&1; then
  ss -ltnp | grep ':8000' || echo "Port 8000 is not listening."
else
  echo "ss is not available."
fi
