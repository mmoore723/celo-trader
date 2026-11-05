#!/bin/bash
# deploy.sh — Build and deploy only the production application to EC2.
# Run from your Mac: ./deploy.sh
#
# Requirements: ssh key configured, EC2_HOST set below.

set -euo pipefail

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
  backtest_exit_sim
  broker
  config
  database
  deploy/application_log_retention.py
  deploy/DEPLOY_GUIDE.md
  deploy/celo-dashboard-logrotate
  deploy/celo-journald.conf
  deploy/release_retention.py
  docs/adr/0004-atomic-tradier-broker-cutover.md
  frontend
  logger_config
  regime_manager
  risk
  router_gates
  scanner
  signal_journal
  signals
  strategy_health
  strategy_router
  tax_engine
  tests
  trading
  strategies
  CLAUDE.md
  README.md
  .gitignore
  alerts.py
  broker_health.py
  candlestick_patterns.py
  celo-dashboard.service
  deploy.sh
  market_data.py
  nginx_celotrader.conf
  requirements.txt
  shadow_ledger.py
)

# Files retired during the August 2026 repository cleanup.  These used to be
# tracked production paths, so `git add` alone would not remove them from EC2.
# Keep this one-time list here until the cleanup has shipped; it makes the
# deletion explicit and prevents stale duplicate modules from surviving a
# release.
RETIRED_PRODUCTION_PATHS=(
  audit_report_2026-07-28.md
  backtest_exit_sim_simplified.py
  backtest_stage1_signals.py
  backtest_trail_multiplier.py
  backtester_1min_entry.py
  build_and_deploy.sh
  celo_dashboard_ec2.log
  scripts
  trading/research
)

FORBIDDEN_DEPLOY_PATHS='^(\.env|user_data/|research/|research_v2/|scripts/research_v2/|research_data/|data/|reports/|audit_reports/|OPRA-|assets/)'

if [ ! -f "$EC2_KEY" ]; then
  echo "Refusing deployment: SSH key not found at $EC2_KEY"
  exit 1
fi

echo "==> Checking patch integrity..."
git diff --check

TEST_PYTHON="${CELO_TEST_PYTHON:-python3}"
if [ -z "${CELO_TEST_PYTHON:-}" ] && [ -x ".venv-paid-research/bin/python" ]; then
  TEST_PYTHON=".venv-paid-research/bin/python"
fi

echo "==> Running the complete production Python acceptance suite..."
"$TEST_PYTHON" tests/run_production_suite.py

echo "==> Linting React frontend..."
cd frontend
npm run lint
cd ..

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

echo "==> Removing retired duplicate and legacy paths..."
git rm -r --ignore-unmatch -- "${RETIRED_PRODUCTION_PATHS[@]}"

# Do not silently include changes that were already staged before this script
# started.  Stop and show the exact paths instead of creating a mixed commit.
STAGED_OUTSIDE_ALLOWLIST="$(
  # Retiring an old research/legacy path is safe and intentional.  Only block
  # an added or modified local artifact from entering a release.
  git diff --cached --name-status \
    | awk '$1 !~ /^D/ {print $NF}' \
    | grep -E "$FORBIDDEN_DEPLOY_PATHS" || true
)"
if [ -n "$STAGED_OUTSIDE_ALLOWLIST" ]; then
  echo "Refusing deployment: research or local artifacts are staged:"
  echo "$STAGED_OUTSIDE_ALLOWLIST"
  echo "Unstage those paths, then run ./deploy.sh again."
  exit 1
fi

echo "==> Production files included in this release:"
git diff --cached --name-only

if git diff --cached --name-only | grep -Eq '(^|/)(\.env|credentials\.enc|users\.db)$'; then
  echo "Refusing deployment: a secret-bearing runtime file is staged."
  exit 1
fi

if ! git diff --cached --quiet; then
  echo "==> Committing production changes..."
  git commit -m "chore: production release $(date +%Y-%m-%d)"
fi

echo "==> Checking and pushing the verified release commit to GitHub main..."
git fetch origin main
if ! git merge-base --is-ancestor origin/main HEAD; then
  echo "Refusing deployment: the verified release is not a fast-forward of origin/main."
  exit 1
fi
if [ "$(git rev-list --count origin/main..HEAD)" -gt 0 ]; then
  git push origin HEAD:main
else
  echo "GitHub main already contains this release."
fi

echo "==> Verifying the EC2 checkout is safe to update..."
REMOTE_TRACKED_DIRTY="$(
  ssh -i "$EC2_KEY" "$EC2_HOST" \
    "cd $EC2_DIR && git status --porcelain --untracked-files=no"
)"
if [ -n "$REMOTE_TRACKED_DIRTY" ]; then
  echo "Refusing deployment: EC2 has tracked changes that a checkout could overwrite:"
  echo "$REMOTE_TRACKED_DIRTY"
  exit 1
fi

echo "==> Pulling on EC2..."
REMOTE_PREVIOUS_SHA="$(ssh -i "$EC2_KEY" "$EC2_HOST" "cd $EC2_DIR && git rev-parse HEAD")"
ssh -i "$EC2_KEY" "$EC2_HOST" "cd $EC2_DIR && git fetch origin main && git checkout main && git pull --ff-only origin main"

echo "==> Retaining previous release assets for already-open browsers..."
ssh -i "$EC2_KEY" "$EC2_HOST" \
  "cd $EC2_DIR && asset_stage=\$(mktemp -d /tmp/celo-assets-retain.XXXXXX) && git archive '$REMOTE_PREVIOUS_SHA' frontend/dist/assets | tar -x -C \"\$asset_stage\" && cp -rn \"\$asset_stage/frontend/dist/assets/.\" frontend/dist/assets/"

echo "==> Installing Python deps on EC2 (full requirements.txt)..."
# Use the venv pip so all packages land inside the venv that uvicorn runs from.
# Previously only fastapi/uvicorn were installed, so yfinance and other deps
# listed in requirements.txt were missing (causing 'No module named yfinance').
ssh -i "$EC2_KEY" "$EC2_HOST" "cd $EC2_DIR && $EC2_DIR/venv/bin/pip install -r requirements.txt -q"

echo "==> Installing the reviewed systemd unit..."
ssh -i "$EC2_KEY" "$EC2_HOST" \
  "sudo install -m 0644 $EC2_DIR/celo-dashboard.service /etc/systemd/system/celo-dashboard.service && sudo systemctl daemon-reload"

echo "==> Installing bounded journal and legacy dashboard-log retention..."
ssh -i "$EC2_KEY" "$EC2_HOST" \
  "sudo install -D -m 0644 $EC2_DIR/deploy/celo-journald.conf /etc/systemd/journald.conf.d/celo-trader-retention.conf && sudo install -m 0644 $EC2_DIR/deploy/celo-dashboard-logrotate /etc/logrotate.d/celo-trader"

echo "==> Verifying required production secrets..."
ssh -i "$EC2_KEY" "$EC2_HOST" \
  "cd $EC2_DIR && test -f .env && test \$(grep -E '^JWT_SECRET=.{32,}$' .env | wc -l) -eq 1 && test \$(grep -E '^ENCRYPTION_KEY=.+$' .env | wc -l) -eq 1"

echo "==> Restarting services on EC2..."
ssh -i "$EC2_KEY" "$EC2_HOST" "sudo systemctl restart celo-dashboard && sudo systemctl status celo-dashboard --no-pager"

echo "==> Verifying deployed health endpoint..."
if ! ssh -i "$EC2_KEY" "$EC2_HOST" "curl --fail --silent --show-error --retry 12 --retry-delay 2 --retry-connrefused http://127.0.0.1:8501/healthz"; then
  echo "Deployment failed health verification."
  echo "Previous server commit: $REMOTE_PREVIOUS_SHA"
  echo "==> Automatically rolling EC2 back to the previous release..."
  if ssh -i "$EC2_KEY" "$EC2_HOST" \
    "cd $EC2_DIR && git checkout --detach '$REMOTE_PREVIOUS_SHA' && $EC2_DIR/venv/bin/pip install -r requirements.txt -q && sudo systemctl restart celo-dashboard" \
    && ssh -i "$EC2_KEY" "$EC2_HOST" \
      "curl --fail --silent --show-error --retry 12 --retry-delay 2 --retry-connrefused http://127.0.0.1:8501/healthz"; then
    echo "Rollback succeeded; EC2 is healthy on $REMOTE_PREVIOUS_SHA."
  else
    echo "CRITICAL: rollback did not restore health. Manual server intervention is required."
  fi
  exit 1
fi

echo "==> Applying post-health storage retention..."
ssh -i "$EC2_KEY" "$EC2_HOST" \
  "cd $EC2_DIR && $EC2_DIR/venv/bin/python deploy/release_retention.py --root /var/tmp --keep 2 && $EC2_DIR/venv/bin/python deploy/application_log_retention.py --root $EC2_DIR/log --retention-days 14 && sudo systemctl restart systemd-journald && sudo journalctl --vacuum-size=512M && sudo /usr/sbin/logrotate --force /etc/logrotate.d/celo-trader"

echo ""
echo "✓ Done. Dashboard: https://celotrader.com"
