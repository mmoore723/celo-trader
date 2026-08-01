#!/bin/bash
# deploy.sh — Build React frontend and push everything to EC2.
# Run from your Mac: ./deploy.sh
#
# Requirements: ssh key configured, EC2_HOST set below.

set -e

EC2_HOST="ec2-user@3.148.153.141"      # ← change this
EC2_DIR="/opt/celo_trader"
# FIX 2026-07-24: every ssh call below was missing -i, so it silently fell
# back to ssh's default identity resolution instead of this key. That
# identity isn't authorized on the server, so "Pulling on EC2" always failed
# with "Permission denied (publickey...)" — every prior deploy.sh run pushed
# to GitHub but never actually reached the live server; the restart step
# never even ran since `set -e` aborted the script right after the failed
# pull. Confirmed via a manual ssh -i that worked immediately after this
# script's bare ssh failed in the same terminal session.
EC2_KEY="${CELO_KEY_FILE:-$HOME/.ssh/celo_trader.pem}"

echo "==> Building React frontend..."
cd frontend
npm run build
cd ..

echo "==> Committing + pushing to GitHub..."
# Never sweep local diagnostics, reports, or secrets into a deployment commit.
# Stage tracked source plus the deliberately versioned frontend build output.
git add -u
git add frontend/dist
if [ -n "$(git ls-files --others --exclude-standard)" ]; then
  echo "==> Leaving untracked local files out of the deployment commit."
fi
git commit -m "chore: frontend build $(date +%Y-%m-%d)" --allow-empty
git push origin main

echo "==> Pulling on EC2..."
ssh -i "$EC2_KEY" "$EC2_HOST" "cd $EC2_DIR && git pull --rebase"

echo "==> Installing Python deps on EC2 (full requirements.txt)..."
# Use the venv pip so all packages land inside the venv that uvicorn runs from.
# Previously only fastapi/uvicorn were installed, so yfinance and other deps
# listed in requirements.txt were missing (causing 'No module named yfinance').
ssh -i "$EC2_KEY" "$EC2_HOST" "cd $EC2_DIR && $EC2_DIR/venv/bin/pip install -r requirements.txt -q"

echo "==> Restarting services on EC2..."
ssh -i "$EC2_KEY" "$EC2_HOST" "sudo systemctl restart celo-dashboard && sudo systemctl status celo-dashboard --no-pager"

echo ""
echo "✓ Done. Dashboard: http://${EC2_HOST}:8501"
