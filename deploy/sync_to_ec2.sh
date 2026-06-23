#!/usr/bin/env bash
# =============================================================================
# Celo Trader — Sync local code to EC2
# Usage:  ./sync_to_ec2.sh <EC2_PUBLIC_IP>
# Example: ./sync_to_ec2.sh 54.123.45.67
#
# Run from your Mac whenever you want to push code changes to the server.
# The bot and dashboard will restart automatically.
# =============================================================================
set -euo pipefail

EC2_IP="${1:-}"
KEY_FILE="${CELO_KEY_FILE:-~/.ssh/celo_trader.pem}"
EC2_USER="ubuntu"
APP_DIR="/opt/celo_trader"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"   # parent of deploy/

if [ -z "$EC2_IP" ]; then
    echo "Usage: ./sync_to_ec2.sh <EC2_PUBLIC_IP>"
    echo "  or set EC2_IP in your environment and run without args."
    exit 1
fi

echo "🚀 Syncing $LOCAL_DIR → $EC2_USER@$EC2_IP:$APP_DIR"

rsync -avz --progress \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.env' \
    --exclude 'venv/' \
    --exclude 'deploy/' \
    --exclude '*.db' \
    --exclude 'bot.log' \
    --exclude 'bot_state.json' \
    -e "ssh -i $KEY_FILE -o StrictHostKeyChecking=no" \
    "$LOCAL_DIR/" \
    "$EC2_USER@$EC2_IP:/tmp/celo_upload/"

# Move files into place with correct ownership
ssh -i "$KEY_FILE" "$EC2_USER@$EC2_IP" \
    "sudo rsync -a /tmp/celo_upload/ $APP_DIR/ && \
     sudo chown -R celo:celo $APP_DIR && \
     sudo chmod -R 755 $APP_DIR && \
     rm -rf /tmp/celo_upload"

echo ""
echo "📦 Installing/updating dependencies..."
ssh -i "$KEY_FILE" "$EC2_USER@$EC2_IP" \
    "sudo -u celo $APP_DIR/venv/bin/pip install -q -r $APP_DIR/requirements.txt"

echo ""
echo "🔄 Restarting services..."
ssh -i "$KEY_FILE" "$EC2_USER@$EC2_IP" \
    "sudo systemctl restart celo-bot celo-dashboard"

echo ""
echo "✅ Deploy complete. Services restarted."
echo "   Dashboard → http://$EC2_IP:8501"
echo ""
echo "   Check bot status:"
echo "   ssh -i $KEY_FILE $EC2_USER@$EC2_IP 'sudo journalctl -u celo-bot -n 50 --no-pager'"
