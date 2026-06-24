#!/bin/bash
# deploy.sh — Build React frontend and push everything to EC2.
# Run from your Mac: ./deploy.sh
#
# Requirements: ssh key configured, EC2_HOST set below.

set -e

EC2_HOST="ec2-user@3.148.153.141"      # ← change this
EC2_DIR="/opt/celo_trader"

echo "==> Building React frontend..."
cd frontend
npm run build
cd ..

echo "==> Committing + pushing to GitHub..."
git add -A
git commit -m "chore: frontend build $(date +%Y-%m-%d)" --allow-empty
git push origin main

echo "==> Pulling on EC2..."
ssh "$EC2_HOST" "cd $EC2_DIR && git pull --rebase"

echo "==> Installing Python deps on EC2..."
ssh "$EC2_HOST" "pip install fastapi 'uvicorn[standard]' python-multipart --break-system-packages -q"

echo "==> Restarting services on EC2..."
ssh "$EC2_HOST" "sudo systemctl restart celo-dashboard && sudo systemctl status celo-dashboard --no-pager"

echo ""
echo "✓ Done. Dashboard: http://${EC2_HOST}:8501"
