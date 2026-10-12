#!/bin/bash
# ============================================================
# run_fetcher.sh — launchd wrapper for the Black Swan fetcher
# Runs bswan_fetcher_v3.py locally (where the network works),
# a few minutes before the 07:? daily Cowork briefing, so the
# briefing always reads fresh daily_readings.json + holdings_prices.json.
# Invoked by ~/Library/LaunchAgents/com.amber.bswan-fetcher.plist
# ============================================================

# Minimal, fixed PATH — no Homebrew dirs on it, so nothing can shadow the
# interpreter. We call the venv's python by ABSOLUTE path (below), which is
# what actually runs the code; PATH here is only for date/echo.
export PATH="/usr/bin:/bin:/usr/sbin:/sbin"

DIR="/Users/aliang/Finance/Stock/bswan"
LOG="$DIR/bswan_fetcher.log"
cd "$DIR" || exit 1

# Pinned virtualenv interpreter (see hardening steps / requirements.lock).
# Absolute path closes both the supply-chain and PATH-hijack risks: only this
# exact, version-locked environment can run the fetcher.
PY="$DIR/.venv/bin/python3"

echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') fetcher start (launchd) =====" >> "$LOG"
if [ ! -x "$PY" ]; then
    echo "ERROR: venv interpreter not found at $PY — run the venv setup steps." >> "$LOG"
    exit 1
fi
"$PY" bswan_fetcher_v3.py >> "$LOG" 2>&1
rc=$?
echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') fetcher done (exit $rc) =====" >> "$LOG"
exit $rc
