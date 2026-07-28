#!/bin/bash
# scripts/sync_trades_db.sh — Periodically pull the live EC2 trades DB down
# to this Mac's project folder, so Claude (sandboxed, can only see mounted
# files) can inspect real trade data without a manual scp round-trip every
# time.
#
# WHY THIS EXISTS: 2026-07 session — an earlier analysis queried the LOCAL
# stale dev copy of trades_paper.db instead of the live EC2 one, wrongly
# concluding trading had stopped for a month (it hadn't — the real DB was on
# EC2 the whole time). Add to project memory: the trades DB lives on EC2
# at $EC2_DIR, NEVER a local file, until this sync exists.
#
# FIX 2026-07-28: this script originally pulled $EC2_DIR/trades_paper.db —
# the LEGACY root-level path. config.py::get_db_path() shows the real,
# actively-written DB lives per-user at
# $EC2_DIR/user_data/{user_id}/trades_paper.db (bot.log confirms:
# "Database initialised at /opt/celo_trader/user_data/admin/trades_paper.db").
# The root-level file is a frozen one-time migration snapshot — database.py's
# init_db() copies OLD → NEW once and never writes back, so the root file
# never gained the new signal_journal table and stopped reflecting new
# trades. Found by querying the synced copy and discovering it had no
# signal_journal table at all, right after the Thinking panel showed
# confidence-floor-blocked signals that made no sense. Assumes single-user
# "admin" — update EC2_USER below if you add real multi-user support.
#
# Meant to run on a schedule (cron/launchd) on YOUR Mac — not on EC2, and
# not in Claude's sandbox, since only your Mac has both the SSH key and a
# path to write into the mounted project folder Claude can see.
#
# TO PAUSE (once trades stabilize and you no longer need frequent pulls):
#   touch ec2_log/SYNC_PAUSED
# TO RESUME:
#   rm ec2_log/SYNC_PAUSED
# TO PERMANENTLY REMOVE the schedule: crontab -e and delete the line, or
# see setup instructions below.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

EC2_HOST="ec2-user@3.148.153.141"
EC2_DIR="/opt/celo_trader"
EC2_USER="admin"                      # per-user data dir on EC2 — see FIX note above
EC2_KEY="${CELO_KEY_FILE:-$HOME/.ssh/celo_trader.pem}"

OUT_DIR="ec2_log"                     # already gitignored (see .gitignore)
LOG_FILE="$OUT_DIR/sync_trades.log"
PAUSE_FILE="$OUT_DIR/SYNC_PAUSED"

mkdir -p "$OUT_DIR"

if [ -f "$PAUSE_FILE" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') paused (found $PAUSE_FILE) — skipping" >> "$LOG_FILE"
    exit 0
fi

# Pull both paper and live DBs from the per-user path — .tmp + mv keeps the
# visible file atomic so nothing reads a half-copied DB mid-transfer.
_pull() {
    local remote_path="$1" local_name="$2"
    if scp -i "$EC2_KEY" -o ConnectTimeout=10 \
        "$EC2_HOST:$remote_path" "$OUT_DIR/$local_name.tmp" 2>>"$LOG_FILE"; then
        mv "$OUT_DIR/$local_name.tmp" "$OUT_DIR/$local_name"
        echo "$(date '+%Y-%m-%d %H:%M:%S') OK  $remote_path -> $OUT_DIR/$local_name" >> "$LOG_FILE"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') FAIL $remote_path (see scp error above)" >> "$LOG_FILE"
        rm -f "$OUT_DIR/$local_name.tmp"
    fi
}

_pull "$EC2_DIR/user_data/$EC2_USER/trades_paper.db" "trades_paper_ec2.db"
_pull "$EC2_DIR/user_data/$EC2_USER/trades_live.db"  "trades_live_ec2.db"
