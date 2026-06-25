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

echo "==> Installing Python deps on EC2 (full requirements.txt)..."
# Use the venv pip so all packages land inside the venv that uvicorn runs from.
# Previously only fastapi/uvicorn were installed, so yfinance and other deps
# listed in requirements.txt were missing (causing 'No module named yfinance').
ssh "$EC2_HOST" "cd $EC2_DIR && $EC2_DIR/venv/bin/pip install -r requirements.txt -q"

echo "==> Restarting services on EC2..."
ssh "$EC2_HOST" "sudo systemctl restart celo-dashboard && sudo systemctl status celo-dashboard --no-pager"

echo ""
echo "✓ Done. Dashboard: http://${EC2_HOST}:8501"
