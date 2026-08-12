#!/bin/bash
# deploy.sh — Build and deploy only the production application to EC2.
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

# The local research workspace is intentionally excluded from application
# releases.  Paid data, archives, generated reports, and tuning runs belong
# in /research and must never be staged by this command. Keep this list
# explicit: adding a new production area is a conscious deployment decision.
PRODUCTION_PATHS=(
  ai_reasoning
  api
  auth
  backtester
  broker
  config
  database
  frontend
  logger_config
  regime_manager
  risk
  router_gates
  scanner
  signal_journal
  signals
  strategy_audit_log
  strategy_health
  strategy_router
  tax_engine
  tests
  trading
  strategies
  .gitignore
  alerts.py
  broker_health.py
  candlestick_patterns.py
  celo-dashboard.service
  deploy.sh
  market_data.py
  nginx_celotrader.conf
  playbook_examples.json
  requirements.txt
  shadow_ledger.py
)

FORBIDDEN_DEPLOY_PATHS='^(research/|research_v2/|scripts/research_v2/|research_data/|data/|reports/|audit_reports/|OPRA-|assets/)'

echo "==> Building React frontend..."
cd frontend
npm run build
cd ..

if [ -n "$(git diff --cached --name-only)" ]; then
  echo "Refusing deployment: you already have staged files."
  echo "Review or unstage them first, then run ./deploy.sh again."
  git diff --cached --name-only
  exit 1
fi

echo "==> Staging only production application paths..."
git add -A -- "${PRODUCTION_PATHS[@]}"

# Do not silently include changes that were already staged before this script
# started.  Stop and show the exact paths instead of creating a mixed commit.
STAGED_OUTSIDE_ALLOWLIST="$(git diff --cached --name-only | grep -E "$FORBIDDEN_DEPLOY_PATHS" || true)"
if [ -n "$STAGED_OUTSIDE_ALLOWLIST" ]; then
  echo "Refusing deployment: research or local artifacts are staged:"
  echo "$STAGED_OUTSIDE_ALLOWLIST"
  echo "Unstage those paths, then run ./deploy.sh again."
  exit 1
fi

echo "==> Production files included in this release:"
git diff --cached --name-only

echo "==> Committing + pushing to GitHub..."
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
