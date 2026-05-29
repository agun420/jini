#!/usr/bin/env bash
#
# install_cron.sh — installs all jini scanner cron jobs on the VM.
# Idempotent: removes old jini-scanner entries first, then re-adds.
#
# Usage:  bash scripts/install_cron.sh
#
set -euo pipefail

JINI="/home/ubuntu/jini"
PY="PYTHONPATH=src /usr/bin/python3"
LOG="$JINI/state"
TAG="# jini-scanner"

# Pull current crontab minus our managed block
crontab -l 2>/dev/null | grep -v "$TAG" > /tmp/cron.new || true

cat >> /tmp/cron.new <<EOF
$TAG  ── engine2 standalone scanner: every 2 min (FAST_MODE skips the social/NLP hang). Refreshes its own dashboard at /engine2/
*/2 4-16 * * 1-5  cd /home/ubuntu/engine2 && ENGINE2_FAST_MODE=1 /usr/bin/python3 -m src.scanner >> $LOG/cron_engine2.log 2>&1
$TAG  ── pre-breakout scanner: every 2 min, pre-market through close (4am-4pm ET = 9-21 UTC roughly; cron is in VM local time)
*/2 4-16 * * 1-5  cd $JINI && $PY scripts/run_prebreakout_scanner.py >> $LOG/cron_prebreakout.log 2>&1
$TAG  ── consensus aggregator: every 5 min during market hours
*/5 9-16 * * 1-5  cd $JINI && $PY scripts/run_consensus_aggregator.py >> $LOG/cron_aggregator.log 2>&1
$TAG  ── swing scanner: once at 8am, 12pm, and 4:15pm ET (daily-bar based, low frequency)
0 8,12 * * 1-5  cd $JINI && $PY scripts/run_swing_scanner.py >> $LOG/cron_swing.log 2>&1
15 16 * * 1-5   cd $JINI && $PY scripts/run_swing_scanner.py >> $LOG/cron_swing.log 2>&1
$TAG  ── outcome backfill: every 15 min during + after market
*/15 9-17 * * 1-5  cd $JINI && $PY scripts/run_consensus_outcome_backfill.py >> $LOG/cron_backfill.log 2>&1
$TAG  ── scorecard: 6pm ET each weekday
0 18 * * 1-5  cd $JINI && $PY scripts/run_consensus_scorecard.py >> $LOG/cron_scorecard.log 2>&1
$TAG  ── dashboard keepalive: restart if not running (checked every 5 min)
*/5 * * * *  pgrep -f run_interactive_dashboard.py >/dev/null || (cd $JINI && DASHBOARD_PORT=5000 $PY scripts/run_interactive_dashboard.py >> $LOG/dashboard.log 2>&1 &)
$TAG  ── dashboard autostart on reboot
@reboot  cd $JINI && DASHBOARD_PORT=5000 $PY scripts/run_interactive_dashboard.py >> $LOG/dashboard.log 2>&1
EOF

crontab /tmp/cron.new
rm -f /tmp/cron.new

echo "Installed jini scanner cron jobs."
echo
TZ_NOW=$(timedatectl show -p Timezone --value 2>/dev/null || echo unknown)
echo "VM timezone is: $TZ_NOW"
if [ "$TZ_NOW" != "America/New_York" ]; then
  echo
  echo "⚠  These cron hours are written in EASTERN time. Your VM is NOT on ET."
  echo "   Run this once so the schedule (and all logs) match US market hours:"
  echo "       sudo timedatectl set-timezone America/New_York"
  echo "   Then re-run: bash scripts/install_cron.sh"
fi
