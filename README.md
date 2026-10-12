# Black Swan Financial Monitor

A personal macro risk monitoring system that tracks early-warning signals for tail-risk events — credit crises, geopolitical shocks, pandemic outbreaks — and scores them against a split hazard model each week.

---

## What it does

**Daily fetcher** (`bswan_fetcher_v3.py`) runs Mon–Fri at 19:25 and collects:

| Signal | Source |
|---|---|
| Market prices (equities, FX, commodities, VIX) | yfinance / Stooq |
| Breakeven inflation, HY spreads, yield curve | FRED API |
| JGB yield curve | Japan MoF CSV |
| 10y Treasury auction bid-to-cover | TreasuryDirect |
| Private credit default rate | Fitch / LSTA |
| Margin debt YoY | FINRA monthly |
| Shiller CAPE | multpl.com |
| Pandemic tier | WHO RSS |

Results are written to `daily_readings.json`.

**Weekly watcher** (`bswan_watcher.py`) runs every Saturday at 09:30. It passes the latest readings to Claude (Opus 5.5 with web search) to produce a 7-part structured analysis: Market Convergence score, Systemic Crisis score, signal-card verdicts, portfolio exposure mapping, and falsifiers. Output is saved as `watch_YYYY-MM-DD.json` and rendered into a self-contained HTML dashboard.

---

## Hazard model

The framework runs a **split hazard model** with two independent sub-scores:

- **Market Convergence (MC)** — correlated drawdown, forced deleveraging, liquidity gates
- **Systemic Crisis (SC)** — institutional solvency, policy transmission, contagion

Both are scored 0–100%. An **effective signal count ≥ 5.5** out of 10 cards triggers a `SYSTEMIC CRISIS` regime. Below that threshold the regime reads `ELEVATED` or `WATCH`.

---

## Setup

### Prerequisites

```bash
pip install anthropic requests yfinance
```

### API keys

Three keys are needed. Store them in `~/.config/insider-scan/env` (see `.env.example`):

| Key | Required for | Get one at |
|---|---|---|
| `ANTHROPIC_API_KEY` | Weekly Claude analysis | console.anthropic.com |
| `ANTHROPIC_WORKSPACE_ID` | Workspace-scoped API access | console.anthropic.com → Workspaces |
| `FRED_API_KEY` | Macro series (inflation, spreads, yield) | fred.stlouisfed.org/docs/api/api_key.html |

Without `FRED_API_KEY`, FRED-backed signals are skipped. Without `ANTHROPIC_API_KEY`, the watcher runs in offline mode (re-renders the dashboard from the last saved analysis).

### launchd (macOS)

Copy the plists to `~/Library/LaunchAgents/` and load them:

```bash
cp com.amber.bswan-fetcher.plist ~/Library/LaunchAgents/
cp com.amber.bswan-watcher.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.amber.bswan-fetcher.plist
launchctl load ~/Library/LaunchAgents/com.amber.bswan-watcher.plist
```

---

## Manual runs

```bash
# Run the fetcher now
python3 bswan_fetcher_v3.py

# Re-run the full weekly analysis
python3 bswan_watcher.py

# Re-render the dashboard from the last saved analysis (no API call)
python3 bswan_watcher.py --dashboard-only
```

---

## What is not in this repo

The following are excluded via `.gitignore` and must never be committed:

- `daily_readings.json` — live portfolio data
- `holdings_prices.json` — portfolio holdings and prices
- `watch_*.json` — weekly analysis output
- `*.log` — fetcher and watcher logs
- Any file containing API keys or account credentials

---

*Not investment advice. This is a personal decision-support tool.*
