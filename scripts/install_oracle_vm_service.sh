#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$(whoami)"

echo "Installing Jini services for repo: ${REPO_DIR}"
echo "Service user: ${USER_NAME}"

sudo tee /etc/systemd/system/jini-runtime.service >/dev/null <<EOF
[Unit]
Description=Jini Always-On Runtime Worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${REPO_DIR}
ExecStart=${REPO_DIR}/scripts/runtime_loop.sh
Restart=always
RestartSec=10
User=${USER_NAME}
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/jini-dashboard.service >/dev/null <<EOF
[Unit]
Description=Jini Local Dashboard Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${REPO_DIR}
ExecStart=${REPO_DIR}/scripts/run_local_dashboard.sh
Restart=always
RestartSec=10
User=${USER_NAME}
Environment=PYTHONUNBUFFERED=1
Environment=DASHBOARD_PORT=8000

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable jini-runtime
sudo systemctl enable jini-dashboard

echo "Installed services:"
echo "  jini-runtime"
echo "  jini-dashboard"
echo
echo "Start them with:"
echo "  sudo systemctl start jini-runtime"
echo "  sudo systemctl start jini-dashboard"
echo
echo "Watch logs with:"
echo "  sudo journalctl -u jini-runtime -f"
echo "  sudo journalctl -u jini-dashboard -f"
