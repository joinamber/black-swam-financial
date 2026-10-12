#!/bin/bash
# ============================================================
# run_watcher.sh — launchd wrapper for the Black Swan weekly watcher
# Runs bswan_watcher.py every Saturday to generate the 7-part
# analysis via Claude API (web_search enabled) and regenerate
# black_swan_dashboard_v4.html.
# ============================================================

export PATH="/usr/bin:/bin:/usr/sbin:/sbin"

DIR="/Users/aliang/Finance/Stock/bswan"
LOG="$DIR/bswan_watcher.log"
cd "$DIR" || exit 1

# Use system python3 which has anthropic, requests, yfinance
PY="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"

# Fallback to any python3 on PATH
if [ ! -x "$PY" ]; then
    PY="$(which python3)"
fi

echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') watcher start (launchd) =====" >> "$LOG"

if [ ! -x "$PY" ]; then
    echo "ERROR: python3 not found" >> "$LOG"
    exit 1
fi

# Load ANTHROPIC_API_KEY from env file if present
ENV_FILE="$HOME/.config/insider-scan/env"
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    set -a; source "$ENV_FILE"; set +a
fi

"$PY" "$DIR/bswan_watcher.py" >> "$LOG" 2>&1
rc=$?
echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') watcher done (exit $rc) =====" >> "$LOG"
exit $rc
