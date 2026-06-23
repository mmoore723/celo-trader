#!/usr/bin/env bash
# =============================================================================
# Celo Trader — EC2 Bootstrap Script
# Run this ONCE on a fresh Ubuntu 22.04 EC2 instance:
#   chmod +x setup_ec2.sh && sudo ./setup_ec2.sh
# =============================================================================
set -euo pipefail

APP_DIR="/opt/celo_trader"
APP_USER="celo"

echo "━━━ [1/7] System packages ━━━"
apt-get update -qq
apt-get install -y -qq \
    python3.11 python3.11-venv python3-pip \
    git curl unzip rsync \
    build-essential libssl-dev libffi-dev \
    sqlite3 \
    nginx

echo "━━━ [2/7] Create app user ━━━"
if ! id "$APP_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$APP_USER"
    echo "User '$APP_USER' created."
fi

echo "━━━ [3/7] Create app directory ━━━"
mkdir -p "$APP_DIR"
chown "$APP_USER:$APP_USER" "$APP_DIR"

echo "━━━ [4/7] Python virtual environment ━━━"
sudo -u "$APP_USER" python3.11 -m venv "$APP_DIR/venv"
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --quiet --upgrade pip

echo "━━━ [5/7] Install Python dependencies ━━━"
if [ -f "$APP_DIR/requirements.txt" ]; then
    sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
    echo "Dependencies installed."
else
    echo "⚠️  requirements.txt not found at $APP_DIR — run sync_to_ec2.sh first, then re-run this script."
fi

echo "━━━ [6/7] systemd services ━━━"

# ── Trading bot service ────────────────────────────────────────────────────────
cat > /etc/systemd/system/celo-bot.service << 'EOF'
[Unit]
Description=Celo Trader — Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=celo
WorkingDirectory=/opt/celo_trader
EnvironmentFile=/opt/celo_trader/.env
ExecStart=/opt/celo_trader/venv/bin/python main.py
Restart=on-failure
RestartSec=15
StandardOutput=journal
StandardError=journal
SyslogIdentifier=celo-bot

# Limits
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

# ── Streamlit dashboard service ────────────────────────────────────────────────
cat > /etc/systemd/system/celo-dashboard.service << 'EOF'
[Unit]
Description=Celo Trader — Streamlit Dashboard
After=network-online.target celo-bot.service
Wants=network-online.target

[Service]
Type=simple
User=celo
WorkingDirectory=/opt/celo_trader
EnvironmentFile=/opt/celo_trader/.env
ExecStart=/opt/celo_trader/venv/bin/streamlit run dashboard.py \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.fileWatcherType none \
    --browser.gatherUsageStats false
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=celo-dashboard

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable celo-bot.service celo-dashboard.service
echo "Services registered."

echo "━━━ [7/7] Firewall (UFW) ━━━"
ufw allow 22/tcp   comment "SSH"
ufw allow 8501/tcp comment "Streamlit dashboard"
ufw --force enable
echo "Firewall configured."

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  Bootstrap complete!                         ║"
echo "║                                              ║"
echo "║  Next steps:                                 ║"
echo "║  1. Upload your code:  ./sync_to_ec2.sh      ║"
echo "║  2. Create .env file:  see DEPLOY_GUIDE.md   ║"
echo "║  3. Start services:                          ║"
echo "║     sudo systemctl start celo-bot            ║"
echo "║     sudo systemctl start celo-dashboard      ║"
echo "╚══════════════════════════════════════════════╝"
