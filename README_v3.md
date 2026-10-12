# Black Swan Monitor — v3 (Split-Regime Hazard Architecture)

Upgrade of the v2 convergence monitor per the Nobel-panel stress test of 9 July 2026.
The point estimate was defensible; the event definition wasn't. v3 fixes the definition.

## What changed from v2

**1. Split terminal regimes.** The old single gauge conflated two different objects.
v3 tracks them separately, because they warrant different portfolio responses:

- **Market Convergence hazard** (~40–50% panel band): correlated drawdown across the
  AI complex, credit, and long-duration sovereigns, with gates and forced selling.
  Positioning-relevant.
- **Systemic Crisis hazard** (~15–25% panel band): loss-absorption fails; the sovereign
  or banking core seizes. Tail-hedge-relevant. Computed as
  `SC = MC × containment-failure factor` where the factor comes from policy space
  (Fed cuts priced for 2026 in `manual.fed_cuts_priced_2026`).

**2. Correlation-weighted signal count.** Two clusters load on one underlying factor
and are capped at 1.5 joint contribution when both fire:
`{energy, fertilizer}` (Hormuz factor) and `{private_credit, ai_nexus}` (AI-credit
factor — BIS: ~8% of private credit now flows to AI-related borrowers).
Two cards in a cluster firing is one signal counted honestly.

**3. Escalator ratchets.** The hazard is a rate, not a fixed prior. Monotone
add-ons (capped +12): Hormuz closure +2/month beyond month 3 (cap 6); weak 30y
auctions (bid-to-cover < 2.20) +2 each (cap 4, **auto-incremented by the fetcher**
when a new weak auction prints); PIK income rising ≥4 consecutive quarters +2.

**4. Pre-registered falsifiers.** Mechanical de-escalation credits, written down
*now* as the defense against confirmation drift. Flip the boolean in
`daily_readings.json → falsifiers` only when the stated evidence prints:

| Falsifier | Credit | Rule |
|---|---|---|
| `ceasefire_and_reopening` | −15 | Strait traffic restored, holding ≥30 days |
| `hyperscaler_two_quarters_held` | −8 | Capex guidance held AND FCF improving, 2 consecutive quarters |
| `true_defaults_rolling_over` | −8 | Fitch/Moody's rate incl. distressed exchanges declines 2 prints |
| `jgb_auctions_normalized` | −5 | Two consecutive 20y+ JGB auctions, normal tails, no intervention |

**5. Three new signal cards** (6 → 9): JGB sovereign snapback (MoF daily CSV +
USD/JPY), AI-credit nexus (IG OAS, QQQ drawdown, manual guidance-cut counter,
Oracle CDS, Korean industrial power YoY as the Chen chip-input channel),
Fertilizer/food (IMF food index + nitrogenous fertilizer PPI via FRED — the
Halvorsen leg, leading indicator for EM political stress).

## Files

| File | Role |
|---|---|
| `black_swan_dashboard_v3.html` | Dashboard. Auto-loads `daily_readings.json`; falls back to embedded seed. |
| `bswan_fetcher_v3.py` | Daily fetcher + **source of truth** for the hazard math and history series. |
| `daily_readings.json` | Data file. `auto` = fetched; `manual` = your judgment fields; `falsifiers` = update rules. |

The dashboard mirrors `compute_model()` in JS for live rendering. Verified identical
outputs on the seed (MC 48 / SC 22 / eff 3.5). **If you change a threshold, change it
in both files.**

## Setup / migration

Same workflow as v2 — drop the three files in your bswan folder alongside the
existing setup scripts, then point the scheduled job at the new fetcher:

```bash
pip3 install requests yfinance          # same deps as v2
# .env with FRED_API_KEY=... is reused as-is
python3 bswan_fetcher_v3.py             # first run
python3 -m http.server 8000             # then open http://localhost:8000/black_swan_dashboard_v3.html
```

In your crontab / Task Scheduler entry, replace `bswan_fetcher.py` with
`bswan_fetcher_v3.py`. v2 files can stay for reference; v3 writes the same
`daily_readings.json` filename with a `"schema": "bswan-v3"` marker.

## Manual-field maintenance cadence

- **Quarterly** (earnings season): `true_default_rate_pct` (Fitch monthly, incl.
  distressed exchanges), `pik_income_share_pct` + `pik_rising_quarters` (BDC
  filings), `hyperscaler_guidance_cuts` (count of Big-5 cutting capex guidance).
- **Monthly**: `oracle_cds_5y_bps`, `kr_industrial_power_yoy_pct`,
  `fed_cuts_priced_2026` (CME FedWatch), `redemption_gates_count`.
- **Event-driven**: `taiwan_tier_manual`, `sea_policy_tier_manual` (MAS decision
  this month is the next high-signal read), falsifier booleans,
  `hormuz_closed_since` (clear it if the falsifier activates).

## Fertilizer note

FRED series used: `PFOODINDEXM` (IMF global food index) and `PCU325311325311`
(US PPI, nitrogenous fertilizer) — robust and automated, monthly. If you prefer
World Bank Pink Sheet urea/DAP levels, the release URL changes monthly, so that
swap is manual: see `FERTILIZER NOTE` in the fetcher.

---
*Panel calibration bands are drawn directly on the dial and the history chart.
The update rule, not the point estimate, is the output that matters.*
