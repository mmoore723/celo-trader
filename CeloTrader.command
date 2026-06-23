#!/bin/bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$SCRIPT_DIR"

# ── Close any previous CeloTrader Terminal windows so old ones don't pile up ──
# macOS always opens .command files in a new window; this script closes every
# OTHER Terminal window whose title contains "CeloTrader.command" before the
# new one takes over. The current window is identified by $TERM_PROGRAM_VERSION
# being freshly spawned (TTY check via $$).
MY_TTY=$(tty 2>/dev/null | sed 's|/dev/||')
osascript 2>/dev/null <<APPLESCRIPT
tell application "Terminal"
    set myTTY to "$MY_TTY"
    repeat with w in windows
        set wName to name of w
        if wName contains "CeloTrader.command" then
            set wTTY to tty of (selected tab of w)
            if wTTY does not contain myTTY then
                close w
            end if
        end if
    end repeat
end tell
APPLESCRIPT

echo "══════════════════════════════════════════════════"
echo "  Celo Trader — Starting Up Workspace Environment"
echo "══════════════════════════════════════════════════"

export PYTHONPATH="$PROJECT_DIR"
cd "$PROJECT_DIR"

# Note if the dashboard was already reachable before we kill it.
# If yes → reload the existing browser tab instead of opening a new one.
DASH_WAS_RUNNING=false
curl -s -f -o /dev/null http://localhost:8501 2>/dev/null && DASH_WAS_RUNNING=true

# HARDCODED AUTOMATIC PORT CLEARING
LOCKED_PID=$(lsof -t -i tcp:8501)
if [ ! -z "$LOCKED_PID" ]; then
    echo "  Ghost instance detected on port 8501 (PID: $LOCKED_PID). Forcing termination..."
    lsof -t -i tcp:8501 | xargs kill -9 2>/dev/null
    sleep 1
fi

# KILL ALL LEFTOVER BOT PROCESSES
echo "  Clearing any leftover Celo Trader processes..."
pkill -9 -f "main.py --paper" 2>/dev/null
pkill -9 -f "streamlit run dashboard.py" 2>/dev/null
sleep 1

# Pick the newest available Python (3.14 → 3.13 → 3.12 → 3.11 → system python3)
PYTHON=""
for _candidate in \
    "/opt/homebrew/bin/python3.14" \
    "/usr/local/bin/python3.14" \
    "/opt/homebrew/bin/python3.13" \
    "/opt/homebrew/bin/python3.12" \
    "/opt/homebrew/bin/python3.11" \
    "/usr/local/bin/python3.11" \
    "/opt/homebrew/bin/python3" \
    "$(which python3)"; do
    if [ -x "$_candidate" ]; then
        PYTHON="$_candidate"
        break
    fi
done
echo "  Using Python: $PYTHON"

$PYTHON -m pip install -q streamlit plotly pandas numpy python-dotenv requests alpaca-py streamlit-autorefresh --break-system-packages

$PYTHON main.py --paper > "bot.log" 2>&1 &
BOT_PID=$!

$PYTHON -m streamlit run "dashboard.py" \
    --server.headless true \
    --server.port 8501 \
    --browser.gatherUsageStats false > "dashboard.log" 2>&1 &
DASH_PID=$!

until $(curl -s -f -o /dev/null http://localhost:8501); do
    sleep 1
done

# ── Reload existing browser tab if one was already open, else open fresh ──────
if [ "$DASH_WAS_RUNNING" = true ]; then
    echo "  Reloading existing browser tab..."
    osascript 2>/dev/null <<RELOAD
tell application "Google Chrome"
    set reloaded to false
    repeat with w in windows
        repeat with t in tabs of w
            if URL of t contains "localhost:8501" then
                reload t
                set index of w to 1
                set active tab index of w to (index of t)
                set reloaded to true
                exit repeat
            end if
        end repeat
        if reloaded then exit repeat
    end repeat
    if not reloaded then open location "http://localhost:8501"
end tell
RELOAD
    # Fallback: if Chrome AppleScript failed, try Safari, then plain open
    if [ $? -ne 0 ]; then
        osascript -e 'tell application "Safari" to set URL of current tab of front window to "http://localhost:8501"' 2>/dev/null \
        || open "http://localhost:8501"
    fi
else
    echo "  Opening browser..."
    open "http://localhost:8501"
fi

cleanup() {
    kill $BOT_PID $DASH_PID 2>/dev/null
    exit 0
}
trap cleanup INT TERM
wait $DASH_PID