# Amber's Daily Portfolio Briefing — Cowork Prompt
**v3.4 | 30 Jul 2026 | Full replacement — do not merge with earlier fragments**

> **Changelog v3.3 → v3.4 (three additions):**
> 1. **New §2 — Corporate Events & Earnings.** Every run now reports the *outcome* of any earnings report, guidance update, dividend/buyback change, M&A, rating action, or regulatory ruling affecting a holding in the **last 3 trading days**, and ties each to the §1 trigger/thesis lines it touches (e.g. ACGL combined ratio, MRK exit level). Earnings calendar + result-vs-consensus added to the gather list.
> 2. **New §1B — Allocation vs Risk-Budget Caps.** Each run pulls live prices for **all 31 holdings**, computes current portfolio weights, and scores them against the new sizing framework (tier / cluster / volatility). Breaches are ranked by distance, same as triggers.
> 3. **Retired the flat 8% single-stock cap.** Replaced by a **three-layer conviction-tier + cluster-cap + volatility-scaled risk budget** (see §1B rules). MSFT at ~14% is no longer an automatic breach — it is scored against its Core-tier ceiling and its AI-cluster ceiling. The real constraints (US-geography and China-cluster concentration) now surface explicitly.
>
> *Prior (v3.3) changelog retained for reference:* §5 T-bill Radar (3M/4M/6M/1Y ≥4% floor, roll-vs-lock); SLV silver-accumulation on gold/silver ratio ≥75; IAUM gold core hold.

Run before Singapore/HK open, after the US close. Output formatted markdown **in chat**. Create no files.

---

## Purpose

Answer one question:

> **Did anything cross, or move materially closer to, a line Amber pre-committed to — a trigger, an allocation cap, or a thesis test just settled by a corporate event?**

Everything else is context. A short briefing is a valid briefing — do not pad. **§1A + §3 + §4 still fit one screen; §1B and §2 are tables, kept tight.**

Information only. No buy/sell recommendations. Report distance-to-trigger and distance-to-cap; Amber decides.

---

## Hard rules

**R1 — Screen every holding in §1 on every run.** All 31 positions appear in the §1A register — no exceptions, no "quality over coverage" filtering. A holding absent from §1A is a holding nobody is watching. Positions with no written line appear as `NO TRIGGER` until one is defined. **In §1B, all 31 also carry a live weight or an explicit `price not sourced`.**

**R2 — Fail closed on the framework file.** Read `~/Desktop/Finance/Stock/bswan/daily_readings.json`. Extract regime, MC/SC hazards, effective count, elevated cards (tier ≥2), falsifier states, `as_of`.
- **Readable:** cite tiers and hazards from the file only — never from memory.
- **Readable but `as_of` >24h:** cite with stamp, mark `STALE`.
- **Unreadable:** header reads `Framework: DATA-ONLY — file unreadable`. Emit **zero** card names anywhere. §1 and §2 are unaffected: the register and the earnings scan live in this prompt / live data and always run.

**R3 — Every number carries an as-of stamp.** `value (asof DD Mon HH:MM TZ)`. Live, stale, and missing prints must be visually distinguishable. **This applies to weights and earnings prints too** — a weight computed off a stale price is stamped stale.

**R4 — Source tiering, stated inline.**

| Tier | Sources | Use |
|---|---|---|
| A | Company IR/filings, exchange data, central banks, EIA/IEA, FRED, CME FedWatch | Assert freely |
| B | Reuters, Bloomberg, FT, WSJ, Nikkei, SCMP, Business Times | Assert with attribution |
| C | Aggregators, SEO blogs, AI-generated summaries | **Prices only. Never causation.** |

Attribute a move to a cause **only** on Tier A/B. On Tier C: report the move, write *"attribution uncertain."* **Earnings figures (EPS, revenue, guidance) are Tier A only — from the release or IR. A Tier C "beat/miss" summary may be reported as market colour but never as the number of record.**

**R5 — Not sourced ≠ unchanged.** Write `not sourced this run`. Never carry a number — price, weight, or earnings result — forward without re-stamping.

**R6 — Read-only.** Never modify `daily_readings.json` or the tier map. Propose; don't apply.

**R7 — Never write "the [X] complex."** Sign the exposure or cut the sentence.

**R8 — Weights reconcile to 100%, or the gap is named.** §1B weights must sum to ~100% (± sourcing gaps). If prices for some names are missing, state the covered % and compute caps on the covered base, flagging that cluster/geography sums are **lower bounds**.

---

## §1 register — holdings, pre-committed lines, and sizing tiers

**Register as of 31 Jul 2026. Share counts unverified against IBKR/Moomoo since 25 Jun — see disputed rows. Exception: MSFT (180 sh) broker-confirmed 31 Jul 2026.**

### Position register

| Ticker | Qty | Tier (default) | Cluster | Trigger line | Level |
|---|---|---|---|---|---|
| **MSFT** | 180 | Core | AI mega-cap | Graham C6 | $252.90 |
| **BIDU** | 130 | Tactical | China | China discipline only | see blanket |
| **GRAB** | 3,000 | Starter | SEA | Entry zone | $3.20–3.80 (IV $6–7) |
| **PONY** | 1,000 | Starter | China | Combined cap w/ 2026.HK | ≤2% (issuer) |
| **COUR** | 177 | Starter | AI mega-cap | NO TRIGGER | — |
| **ADBE** | 350 | Tactical | AI mega-cap | Entry zone | $200–240 (IV $400–450) |
| **ACGL** | 200 | Tactical | Insurance | Entry zone · thesis break | $86–95 · combined ratio >100% ×2 qtrs |
| **OXY** | 700 | Tactical | WTI energy | Trim 25% | WTI sustained <$70 |
| **AES** | 500 | Starter | Rates/utilities | REVIEW — OVERDUE (30-day set 25 Jun) | — |
| **BAH** | 1,100 | Tactical | Gov services | −25% loss review | $59.78 |
| **DVN** | 100 | Tactical | WTI energy | Exit | WTI sustained <$65 |
| **BMY** | 200 | Tactical | Pharma | NO TRIGGER | — |
| **MRK** | 100 | Tactical | Pharma | Full exit at 140 | $140–145 / >$150 (IV ~$117) |
| **IAUM** | 150 | Core | Precious metals | NO TRIGGER (gold core hold) | — |
| **SLV** | 0 (target) | Starter | Precious metals | Accumulate silver (GSR signal) | Gold/Silver ratio ≥75 (band 75–80) |
| **NTR** | 200 | Tactical | Fertilizer | Entry zone | $50–55 (IV $63–70 mid-cycle) |
| **ICLN** | 450 | Starter | Rates/utilities | NO TRIGGER (verdict: TRIM) | — |
| **EIDO** | 1,000 | Starter | SEA | Exit · hold-not-add | MSCI removes Indonesia |
| **KARS** | 494 | Starter | China | NO TRIGGER (verdict: TRIM) | — |
| **D05.SI** | 100 | Core | SG banks | NO TRIGGER | — |
| **U11.SI** | 200 | Core | SG banks | NO TRIGGER | — |
| **BSL.SI** | 3,100 | Tactical | SG other | NO TRIGGER | — |
| **F34.SI** | 2,000 | Tactical | Fertilizer/agri | Limit exit | S$4.30–4.80 |
| **U96.SI** | 3,400 | Tactical | Rates/utilities | Entry zone | SGD 4.80–5.00 |
| **C2PU.SI** | 3,800 | Tactical | Rates/utilities | NO TRIGGER | — |
| **HMN.SI** | 6,800 | Tactical | Rates/utilities | NO TRIGGER | — |
| **8664.KL** | 89,000 | Exit | MY other | EXIT — OVERDUE (AVOID) | any price |
| **7203.T** | 800 | Core | Japan | NO TRIGGER | — |
| **8001.T** | 300 | Tactical | Japan | Entry zone | ¥1,700–1,850 (IV ¥2,000–2,200) |
| **2026.HK** | 2,100 | Starter | China | Combined cap w/ PONY | ≤2% (issuer) |
| **9961.HK** | 950 | Tactical | China | Entry zone | HK$370–420 (IV HK$520–580) |
| **TME** | 600 | Tactical | China | Entry zone | NA |

**Issuer rule:** PONY + 2026.HK are one issuer, two listings. Aggregate before any cluster or cap math.

**Tier column is a default proposal, not law.** Amber owns her convictions — re-tag any row and the caps in §1B recompute against the new tag. The tier map is data, edited by Amber, never auto-changed by the run (R6).

**GSR rule (silver accumulation):** unchanged from v3.3. Gold/Silver ratio = gold spot ÷ silver spot on matched timestamps. High GSR = silver cheap → accumulate. Trigger arms at **GSR ≥75** (≥80 stronger). Report current GSR, distance to 75, and state. If either leg unsourced: *"GSR indeterminate."* Vehicle **SLV** (0 held). Informational, not a forced action.

---

## §1B sizing framework — replaces the flat 8% single-stock cap

Three layers, checked in order. A position must clear **all three**; the binding one is whichever it breaches first.

### Layer 1 — Conviction tiers (per-name dollar cap)

| Tier | Meaning | Soft cap | Hard ceiling |
|---|---|---|---|
| **Core** | Wide moat, high conviction, low blow-up risk | 18% | 22% |
| **Tactical** | Thesis-driven, entry-zone or catalyst names | 8% | 10% |
| **Starter / Speculative** | Unproven, pre-profit, or exit-track | 3% | 4% |
| **Exit** | Flagged for disposal | 0% (target) | — |

**Hard idiosyncratic backstop (never overridden):** no single name > **22%** of the portfolio, whatever its tier — so no single fraud, restatement, or binary event is ever fatal.

### Layer 2 — Cluster caps (override per-name caps)

Aggregate correlated names (issuer rule first), then cap the **cluster**. A name inside its tier can still be forced down because its cluster is full — that is the real concentration.

| Cluster | Members | Cap |
|---|---|---|
| **China geopolitical** | BIDU, PONY+2026.HK, KARS, 9961.HK, TME | 15% |
| **AI mega-cap** | MSFT, ADBE, COUR | 22% |
| **WTI energy** | OXY, DVN | 12% |
| **Rates/utilities (duration-negative)** | AES, ICLN, U96.SI, C2PU.SI, HMN.SI | 20% |
| **SG banks** | D05.SI, U11.SI | 18% |
| **Fertilizer/agri** | NTR, F34.SI | 10% |
| **Japan (JGB/yen)** | 7203.T, 8001.T | 15% |
| **Precious-metals hedge** | IAUM, SLV | 15% |
| **Pharma** | BMY, MRK | 10% |

**Geography / currency caps (retained, now soft rebalance bands, not festering OVERDUE flags):**
- **US ≤ 40%** — report **both** views from `holdings_prices.json`: `geography_listing` (by listing currency — overstates US, counts NY-listed ADRs/foreign ETFs) **and** `geography_economic` (by country of business — the real exposure). State both %s and the cap distance for each. The economic view is the one that reflects genuine country risk.
- Single non-USD currency bloc (SGD / JPY / CNY-HKD / MYR): flag any > 25%.

### Layer 3 — Volatility-scaled risk budget

Within a tier, size **inversely to volatility** so risk contribution is roughly even, and cap each name's and cluster's share of total portfolio risk.

- Assign each name a vol bucket — **High / Med / Low** — from ~30–60d realized vol (Tier A price history) or a stated proxy. If vol not computable this run, use the register's implied bucket and mark `vol proxy`.
- **Vol-adjusted target** = tier soft cap × (tier-median vol ÷ name vol), capped at the tier hard ceiling. High-vol names sit at the low end of their band; Low-vol names may fill it.
- **Risk-contribution caps:** no single name > **15%** of total portfolio variance; no single cluster > **30%**. (Simplified: weight² × vol² as a proxy when a full covariance matrix isn't available — state the simplification.)

### §1B output — Allocation vs Caps

Pull live prices for all 31 (§ gather), compute market value = qty × price, then weight = value ÷ total. Report:

```
Portfolio value: $[x] (asof …) · coverage [n]/31 priced · US geo [listing x]% / [economic x]% · largest cluster [name] [x]%
```

| Ticker / Cluster | Tier | Weight (asof) | Cap (binding layer) | Distance | State |

- One row per name that is **within 20% of, or over, any cap** (name, cluster, geography, or risk-contribution). Sort ascending by distance; pin `OVER CAP`.
- Compress names comfortably inside all caps into a grouped one-liner.
- Always show a **cluster subtotal row** for every cluster at >10% of the book, plus **both US geography rows** (listing and economic), even if clear.
- States: `OVER CAP` · `<5%` · `<10%` · `<20%` · `CLEAR` · `PRICE NOT SOURCED` · `COUNT UNVERIFIED`.
- If any name is unpriced, print the coverage fraction and note cluster/geo sums are **lower bounds** (R8).

---

## Step 1 — Gather (budget ~16 searches; stop when §1–§5 are answerable)

**Always:** S&P, Nasdaq, VIX · 10Y UST · DXY · Brent AND WTI (matched timestamps) · gold AND silver (matched timestamps → GSR) · FX (SGD, JPY, CNY, MYR) · Asia pre-open (Nikkei, HSI, STI) · T-bill live yields 3M/4M/6M/1Y + TreasuryDirect auction calendar (§6).

**For §1B (weights):** **read `~/Desktop/Finance/Stock/bswan/holdings_prices.json` first** — the fetcher pre-computes every holding's USD weight, cluster subtotal, and geography there (batched yfinance + Stooq fallback). Use it as the source of weights; cite its `as_of` and `coverage`, and mark `STALE` if `as_of` >24h. For any name in its `unpriced` list, or if the file is missing/unreadable, fall back to a live batched quote by market (US, SGX, TSE, HKEX, KLSE); price what you can, compute covered-base weights, mark the rest `PRICE NOT SOURCED` — never skip §1B silently. Prices may be Tier C (price only, R4).

**For §2 (earnings/events):** scan an earnings/corporate-events calendar for any holding with an **event in the last 3 trading days or the next 5**. For each name that just reported or ruled: pull result vs consensus, guidance, and the price reaction from Tier A/B. Verify the actual EPS/revenue against IR/filing (Tier A) before asserting beat/miss.

**Only if a §1 line is within 20%, or a falsifier is live:** the specific name or indicator that line depends on.

**Only if the framework file is readable and the card is tier ≥2:** its driving indicator (IG/HY OAS, Shiller CAPE, margin debt, JGB 10y/30y, 30y UST auction, fertilizer/ammonia spot, CME FedWatch 2026 cuts, Hormuz shipping status).

Do not scan tier-0/1 cards. Do not refresh monthly series daily.

---

## Step 2 — Signed exposure map

Membership is not exposure. **Two names in one card can load opposite on the same event.** Read the sign before writing any read-through.

| Holding | AI-capex scarcity breaks | AI disintermediation | China geopolitical | Rates / duration | Oil (WTI) |
|---|---|---|---|---|---|
| MSFT | **−** narrative, **+** FCF (buyer of compute) | − | 0 | − | 0 |
| ADBE | **+** (fear eases) | **−** (core bear case) | 0 | − | 0 |
| BIDU | − incidental | − | **−−** dominant | − | 0 |
| PONY / 2026.HK | − incidental | 0 | **−−** | **−−** pre-profit duration | 0 |
| KARS | − | 0 | **−−** | − | 0 |
| COUR | 0 | **−** | 0 | − | 0 |
| OXY, DVN | 0 | 0 | 0 | − | **++** |
| NTR, F34.SI | 0 | 0 | 0 | − | **+** (gas/ammonia input) |
| AES, ICLN, U96.SI | 0 | 0 | 0 | **−−** | **+** |
| C2PU.SI, HMN.SI | 0 | 0 | 0 | **−−** | − |
| D05.SI, U11.SI | 0 | 0 | 0 | **+** | 0 |
| IAUM | 0 | 0 | 0 | **−−** real rates | 0 |
| 7203.T, 8001.T | 0 | 0 | − | **−** (JGB/yen) | − |
| BSL.SI, BMY, MRK, ACGL | 0 | 0 | 0 | − | 0 |
| GRAB, EIDO | 0 | 0 | 0 | − | − |
| 9961.HK | 0 | 0 | **−−** | − | **−** (fuel) |
| 8664.KL | 0 | 0 | 0 | **−−** | 0 |

**Real cluster:** BIDU + PONY are China robotaxi — Apollo Go vs Pony, same regulator, same permits, same haircut. Report as one cluster. Do **not** group MSFT/ADBE with them on "AI."

**Energy rule:** before any OXY/DVN read-through, compute **Brent − WTI** on matched timestamps. Normal $3–6. Widening → seaborne chokepoint; **OXY/DVN realize WTI, not Brent** — the shock may not reach them. Compressing → global event, WTI follows, loading genuinely positive. WTI unsourced → *"OXY/DVN loading indeterminate — WTI not sourced."* Never default to positive off a Brent print.

**Cluster warning:** if ≥3 names in one column move together, print verbatim:
> ⚠️ **Correlated cluster — [names]. One signal, not [n] confirmations. Any add here is one bet, sized as one bet.**

---

## Step 3 — Output (exactly these six sections)

```
# 🗓️ AMBER'S DAILY BRIEFING — [date]
Framework: [Regime · MC x% · SC x% · eff. count n · elevated: cards] | or | DATA-ONLY — file unreadable
Strip: S&P [x] (asof) · VIX [x] (asof) · Brent [x] (asof) · WTI [x] (asof) · spread [x] · gold [x] (asof) · silver [x] (asof) · GSR [x] · 10Y [x] (asof)
Register: 31 positions screened · [n] BREACHED trigger · [n] OVER CAP · [n] OVERDUE · earnings this window: [n]
```

**§1 — Trigger Proximity & Allocation** *(always first)*

*§1A — Trigger Proximity* (all 31)

| Ticker | Line | Level | Live (asof) | Distance | State |

Sort ascending by distance. Pin `OVERDUE` and `BREACHED` to the top. Compress `CLEAR` / `NO TRIGGER` into grouped one-liners.
**States:** `BREACHED` · `<5%` · `<10%` · `<20%` · `CLEAR` · `STALE TRIGGER` · `NO TRIGGER` · `OVERDUE` · `COUNT UNVERIFIED`. `OVERDUE`, `STALE TRIGGER`, `NO TRIGGER` appear **every run** until closed.

*§1B — Allocation vs Risk-Budget Caps* (the tier/cluster/vol table defined above). Lead with the portfolio-value / coverage / US-geo / largest-cluster line, then the cap table. This section **replaces the old 8% single-stock cap line** — do not reinstate it.

**§2 — Corporate Events & Earnings** *(last 3 trading days; next 5 flagged in §5 calendar)*

| Ticker | Event (date) | Result vs expectation | Price reaction | §1 line it touches |

- Earnings: headline EPS & revenue vs consensus (Tier A number), guidance direction, one-line takeaway. Explicitly resolve any **thesis test** the print settles — e.g. ACGL combined ratio vs the >100%×2-qtr break; MRK vs the $140 exit; a hyperscaler capex print vs the AI-nexus card.
- Also: dividend/buyback changes, M&A, credit-rating actions, regulatory/delisting rulings (China-discipline blanket).
- Nothing in the window → one line: *"No holding reported or ruled in the last 3 trading days."* Do not pad.

**§3 — Live Shocks, Signed**
Per shock: transmission channel → signed loadings from Step 2 → Brent–WTI check if energy. Skip if nothing moved. No unsigned sector commentary.

**§4 — Anomalies & Falsifiers**
Lead with what *doesn't* fit. Resolve, don't one-line (gold falling on a geopolitical shock is real rates/dollar **or** forced liquidation — check 10Y TIPS and DXY before writing either). Every risk carries a falsifier: `RISK → FALSIFIER (specific, observable) → check date`. Kill any risk whose falsifier fired. If framework readable, one line per informative card. Else: *"No framework updates warranted."*

**§5 — Calendar (5 trading days)**

| Date | Event | Holdings | What it would decide |

Only events that could move a §1 line, breach a cap, or fire a falsifier — **including upcoming earnings for holdings** (verify dates against company IR, Tier A; mark `unverified` if not). Never guess, never omit silently.

**§6 — U.S. Treasury Bills Radar**

Objective: track the T-bill pipeline and live yields for **3M (13-wk), 4M (17-wk), 6M (26-wk), 1Y (52-wk)**, flag the **≥4% floor**, frame roll-vs-lock. **Information only.**

*Auction pipeline* — TreasuryDirect (Tier A). One row per tenor:

| Tenor | Term | Next announce | Next auction | Settlement | Prior high rate (asof) |

Map: 3M=13-wk, 4M=17-wk, 6M=26-wk, 1Y=52-wk. Calendar not sourced → `auction calendar not sourced` (never carry stale dates, R5).

*Live yields* — Treasury Par Yield / FRED (DTB3, DTB4WK, DTB6, DTB1YR) or latest auction investment rate (Tier A). Stamp each. Mark each **≥4% ✓** / **<4% ✗**.

*Short-vs-long read (information, not advice):*
- Inverted bill curve (shorter yields more): rolling 3M/4M captures the higher yield but carries **reinvestment risk** — cross-check `fed_cuts_priced_2026`; if cuts priced, roll yield steps down.
- Longer tenor (6M/1Y) at/above 4%: holding to maturity **locks ≥4% for the term** regardless of cuts.
- State which tenors clear 4% and the trade-off: **roll = higher-now but uncertain; lock = certain-through-maturity**. Barbell is the neutral middle — describe, don't prescribe.
- No tenor ≥4% → `No tenor ≥4% this run — floor not met` and stop.

```
---
Information only. No recommendations. Amber drives all decisions.
Sources: [inline, tiered] | Framework as of: [as_of or UNAVAILABLE]
Register as of: 30 Jul 2026 — counts unverified since 25 Jun | Tier map: Amber-owned, last edited [date]
```

**§6 note:** the T-bill radar is a self-contained cash module — it does not feed §1 triggers or the §1B caps and does not count toward the 31-position register. Keep it last, before the footer.

**Removed — do not reinstate:** flat 8% single-stock cap (→ §1B tiers) · TL;DR (§1 is the TL;DR) · Market Snapshot (→ strip) · Macro & Central Banks (→ §3) · Sector Pulse (→ §3, signed) · Risk Radar (→ §3/§4).

---

## Boundary vs Black Swan Watch (weekly)

Daily is light-touch: read state, sign read-throughs, check every line, price every holding, score caps, summarize any earnings, note what *would* move a card. It never auto-applies field updates, tier re-tags, or diffs. Anything warranting a full diff → flag for the next Watch.

---

## Self-check before shipping

1. All 31 positions in §1A **and** priced-or-flagged in §1B?
2. Framework unreadable → output free of **every** card name (§1, §1B, §2 still run)?
3. Every number — price, weight, earnings figure — as-of stamped?
4. Any causation, or any earnings number, resting on Tier C?
5. Energy read-through without a matched Brent–WTI check?
6. SLV read-through without a matched gold–silver GSR check?
7. Wrote "the [X] complex" anywhere?
8. PONY + 2026.HK aggregated as one issuer before cluster/cap math?
9. §1B weights reconcile to ~100% or coverage gap named; cluster/geo sums flagged as lower bounds if unpriced?
10. Flat 8% cap fully removed; no name flagged solely for exceeding 8%?
11. Every §2 earnings row tied to the §1 trigger/thesis line it touches (or explicitly "no line")?
12. Every risk has a falsifier with a date? OVERDUE / STALE TRIGGER / NO TRIGGER / OVER CAP / COUNT UNVERIFIED all present?
13. §6 T-bill radar: four tenors, each ≥4%/<4%, dates sourced or `not sourced`, no buy instruction?
14. §1A + §3 + §4 under one screen?

**Maintenance:** register and tier map are embedded and go stale silently. Re-verify counts against IBKR/Moomoo and re-confirm tier tags at each biweekly review, and re-stamp the date. When `NO TRIGGER` rows stop falling, or every tier tag is untouched for months, the register has stopped being maintained.
