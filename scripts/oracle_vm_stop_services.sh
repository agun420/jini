#!/usr/bin/env bash
set -euo pipefail

echo "Stopping Jini Oracle VM services..."

sudo systemctl stop jini-runtime || true
sudo systemctl stop jini-dashboard || true

echo "Stopped."
