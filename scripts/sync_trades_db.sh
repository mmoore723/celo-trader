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
#
# ADDED 2026-07-28: also pull a bot.log tail. Previously this script only
# synced the two trades DBs — bot.log had to be scp'd by hand, and the one
# time it was needed mid-debug the local copy was 4 days stale. bot.log
# itself is 49MB+ and growing, so this pulls just the last N lines over SSH
# (`tail` runs on EC2, only the tail text crosses the wire) instead of
# scp-ing the whole file every 15 minutes.
#
# FIX (same day): first attempt pointed at $EC2_DIR/bot.log (repo root) —
# doesn't exist. logger_config.py / config.py::LOG_PATH show the real path
# is $EC2_DIR/log/bot.log (a "log" subdirectory). Same mistake shape as the
# trades-DB root-vs-subpath bug above — checked the code this time instead
# of assuming the layout matched the local dev copy.

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

# Tail bot.log over SSH (not scp) — see 2026-07-28 note above. Same .tmp+mv
# atomicity as _pull() so nothing reads a half-written tail.
BOT_LOG_TAIL_LINES=3000
if ssh -i "$EC2_KEY" -o ConnectTimeout=10 "$EC2_HOST" \
    "tail -$BOT_LOG_TAIL_LINES $EC2_DIR/log/bot.log" > "$OUT_DIR/bot_tail.log.tmp" 2>>"$LOG_FILE"; then
    mv "$OUT_DIR/bot_tail.log.tmp" "$OUT_DIR/bot_tail.log"
    echo "$(date '+%Y-%m-%d %H:%M:%S') OK  bot.log (last $BOT_LOG_TAIL_LINES lines) -> $OUT_DIR/bot_tail.log" >> "$LOG_FILE"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') FAIL bot.log tail (see ssh error above)" >> "$LOG_FILE"
    rm -f "$OUT_DIR/bot_tail.log.tmp"
fi
