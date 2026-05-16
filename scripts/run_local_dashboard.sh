#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../docs"

PORT="${DASHBOARD_PORT:-8000}"

echo "Serving dashboard at http://0.0.0.0:${PORT}"
python3 -m http.server "${PORT}" --bind 0.0.0.0
