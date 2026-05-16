#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

git add docs/data/prediction_engine state/prediction_engine
git commit -m "Update Jini runtime dashboard data" || exit 0
git push
