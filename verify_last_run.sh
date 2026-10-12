#!/bin/bash
# verify_last_run.sh — check whether the com.amber.bswan-fetcher launchd job
# ran successfully this morning and left fresh data behind.
# Usage:  bash ~/Finance/Stock/bswan/verify_last_run.sh

set -uo pipefail
DIR="$HOME/Finance/Stock/bswan"
LABEL="com.amber.bswan-fetcher"
cd "$DIR" || { echo "❌ cannot cd to $DIR"; exit 1; }

echo "================ 1. launchd job state ================"
# Prints last exit code + PID if loaded; error if not registered.
if launchctl list | grep -q "$LABEL"; then
    launchctl list | grep -E "PID|$LABEL" | head -1
    launchctl list "$LABEL" 2>/dev/null | grep -E '"(PID|LastExitStatus)"' \
        || echo "(no PID/LastExitStatus keys — job idle between runs, normal)"
else
    echo "❌ $LABEL is NOT loaded. Reload with:"
    echo "   launchctl bootstrap gui/\$(id -u) $DIR/$LABEL.plist"
fi

echo
echo "================ 2. last fetcher run (from log) ================"
# Show the most recent start→done block.
awk '/fetcher start/{buf=""} {buf=buf$0"\n"} /fetcher done/{last=buf} END{printf "%s", last}' \
    bswan_fetcher.log 2>/dev/null || echo "no bswan_fetcher.log"

echo
echo "================ 3. did it run TODAY? ================"
TODAY=$(date +%Y-%m-%d)
if grep -q "$TODAY.*fetcher done (exit 0)" bswan_fetcher.log 2>/dev/null; then
    echo "✅ successful run logged today ($TODAY)"
else
    echo "⚠️  no 'exit 0' run logged today ($TODAY) — check section 2 above"
fi

echo
echo "================ 4. data file freshness ================"
for f in daily_readings.json holdings_prices.json; do
    if [ -f "$f" ]; then
        mtime=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M:%S" "$f")
        asof=$(python3 -c "import json,sys;print(json.load(open('$f')).get('as_of','?'))" 2>/dev/null)
        echo "$f  | file mtime: $mtime  | as_of: $asof"
    else
        echo "$f  | ❌ MISSING"
    fi
done
echo "coverage/value:"
python3 -c "import json;d=json.load(open('holdings_prices.json'));print('  ',d.get('coverage'),'| \$'+format(d.get('portfolio_value_usd',0),',.2f'))" 2>/dev/null

echo
echo "================ 5. recent launchd errors ================"
if [ -s launchd.err.log ]; then
    echo "last 5 lines of launchd.err.log (stale Desktop-path errors are pre-v3.5, ignore):"
    tail -5 launchd.err.log
else
    echo "✅ launchd.err.log empty"
fi
