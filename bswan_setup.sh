#!/usr/bin/env bash
# ============================================================
# bswan_setup.sh  —  One-time setup for Black Swan fetcher
# Works on macOS and Linux (Ubuntu/Debian)
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FETCHER="$SCRIPT_DIR/bswan_fetcher.py"
LOG="$SCRIPT_DIR/bswan_fetcher.log"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   Black Swan Daily Convergence Monitor — Setup           ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── 1. Check Python 3 ────────────────────────────────────────
PYTHON=$(command -v python3 || command -v python)
if [ -z "$PYTHON" ]; then
  echo "✗ Python 3 not found. Install from https://python.org"
  exit 1
fi
echo "✓ Python: $($PYTHON --version)"

# ── 2. Install dependencies ───────────────────────────────────
echo ""
echo "Installing Python dependencies..."
$PYTHON -m pip install --upgrade requests yfinance schedule --quiet
echo "✓ Dependencies installed"

# ── 3. FRED API key ───────────────────────────────────────────
echo ""
echo "────────────────────────────────────────────────────────────"
echo "FRED API key (free) — needed for:"
echo "  10y yield, breakeven inflation, HY OAS spreads"
echo ""
echo "  Get a free key at: https://fred.stlouisfed.org/docs/api/api_key.html"
echo "  (takes 30 seconds — just an email address)"
echo ""
read -rp "Paste your FRED API key (or press Enter to skip): " FRED_KEY

if [ -n "$FRED_KEY" ]; then
  # Write to a .env file that the fetcher loads
  echo "FRED_API_KEY=$FRED_KEY" > "$SCRIPT_DIR/.env"
  echo "✓ FRED key saved to .env"
else
  echo "⚠  Skipped — FRED indicators will hold last saved values"
fi

# ── 4. Register cron at 07:00 ─────────────────────────────────
echo ""
echo "────────────────────────────────────────────────────────────"
echo "Registering 7:00am daily cron job..."

# Load FRED key in cron via the .env file
CRON_ENV=""
if [ -f "$SCRIPT_DIR/.env" ]; then
  CRON_ENV="set -a; source $SCRIPT_DIR/.env; set +a &&"
fi

CRON_CMD="0 7 * * 1-5 $CRON_ENV $PYTHON $FETCHER >> $LOG 2>&1"

# Remove any existing bswan cron line, then add fresh
( crontab -l 2>/dev/null | grep -v "bswan_fetcher"; echo "# bswan daily brief — runs Mon–Fri 07:00"; echo "$CRON_CMD" ) | crontab -

echo "✓ Cron job registered:"
echo "   $CRON_CMD"
echo ""
echo "Verify with:  crontab -l | grep bswan"

# ── 5. Run once now ───────────────────────────────────────────
echo ""
echo "────────────────────────────────────────────────────────────"
read -rp "Run the fetcher right now to generate today's data? [Y/n]: " RUN_NOW
if [[ "$RUN_NOW" =~ ^[Nn] ]]; then
  echo "Skipped. Will run automatically tomorrow at 07:00."
else
  echo "Fetching..."
  if [ -n "$FRED_KEY" ]; then
    FRED_API_KEY="$FRED_KEY" $PYTHON "$FETCHER"
  else
    $PYTHON "$FETCHER"
  fi
  echo ""
  if [ -f "$SCRIPT_DIR/daily_readings.json" ]; then
    echo "✓ daily_readings.json written"
    echo "  Open black_swan_dashboard.html in your browser"
  fi
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Setup complete. Dashboard refreshes at 07:00 Mon–Fri."
echo ""
echo "  Manual run any time:  python3 $FETCHER"
echo "  View logs:            tail -f $LOG"
echo "  Edit manual fields:   open daily_readings.json"
echo "═══════════════════════════════════════════════════════════"
echo ""
