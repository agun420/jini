#!/usr/bin/env bash
set -euo pipefail

echo "Starting Jini Oracle VM services..."

sudo systemctl daemon-reload
sudo systemctl start jini-runtime
sudo systemctl start jini-dashboard

echo
echo "Runtime service:"
sudo systemctl status jini-runtime --no-pager || true

echo
echo "Dashboard service:"
sudo systemctl status jini-dashboard --no-pager || true

echo
echo "Started. Watch logs with:"
echo "sudo journalctl -u jini-runtime -f"
echo "sudo journalctl -u jini-dashboard -f"
