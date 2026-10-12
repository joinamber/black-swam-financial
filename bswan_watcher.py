#!/usr/bin/env python3
"""
bswan_watcher.py — Black Swan Weekly Analysis Runner, v1.0
===========================================================
Runs every Saturday.  Reads the current daily_readings.json and, WHEN AN API KEY IS
AVAILABLE, calls the Anthropic API (claude-opus-5-5 + built-in web_search) to perform
the 7-part Black Swan analysis, saves watch_YYYY-MM-DD.json, and regenerates
black_swan_dashboard_v4.html.

The API is OPTIONAL.  With no key, no SDK, --offline, or if the live call fails for any
reason (auth, 400, max_tokens...), the run still succeeds: it re-renders the dashboard
from the current daily_readings.json plus the most recent saved analysis, with a banner
saying the narrative was not refreshed.  Exit code is 0 either way; the mode and reason
are logged and written to watcher_status.json.

Usage:
    python3 bswan_watcher.py                  # today's date
    python3 bswan_watcher.py --date 2026-09-27
    python3 bswan_watcher.py --dashboard-only  # re-render without re-running Claude
    python3 bswan_watcher.py --offline         # force offline even if a key is set (or BSWAN_OFFLINE=1)
    ANTHROPIC_API_KEY=sk-ant-... python3 bswan_watcher.py   # live analysis (optional)

Optional:  pip install anthropic   (only needed for the live analysis)
Output:    watch_YYYY-MM-DD.json  +  black_swan_dashboard_v4.html
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import html as html_mod
import json
import logging
import os
import re
import sys
from pathlib import Path

try:
    import anthropic
except ImportError:          # the API is optional: offline mode needs no SDK
    anthropic = None

def _load_env():
    """Load KEY=VALUE lines from ~/.config/insider-scan/env without overriding the real
    environment.  Loads every variable (not just the API key) so ANTHROPIC_WORKSPACE_ID,
    BSWAN_MODEL etc. are honoured on manual runs too — an exported ANTHROPIC_API_KEY used
    to short-circuit this and drop the workspace header (-> 400)."""
    env_file = os.path.expanduser("~/.config/insider-scan/env")
    if not os.path.exists(env_file):
        return
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

_load_env()

DIR = Path(__file__).parent
READINGS = DIR / "daily_readings.json"
DASHBOARD = DIR / "black_swan_dashboard_v4.html"
MODEL = os.environ.get("BSWAN_MODEL", "claude-opus-5-5")
LOG = DIR / "bswan_watcher.log"

# FileHandler covers the log file; StreamHandler only when running interactively
# (avoids duplicates when run_watcher.sh redirects stderr to the same log file)
_handlers: list[logging.Handler] = [logging.FileHandler(LOG)]
if sys.stderr.isatty():
    _handlers.append(logging.StreamHandler())
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=_handlers,
)
log = logging.getLogger("bswan_watcher")

# --------------------------------------------------------------------------- #
#  System prompt (condensed from Black-swan-review.md)                        #
# --------------------------------------------------------------------------- #
SYSTEM = """You are a seasoned economist and macro analyst who has navigated Black Swan
events firsthand — the 1997 Asian Financial Crisis, the 2001 dot-com bust,
the 2008 GFC, COVID-19, and the 2022 crypto/rate shock. Your edge is
unconventional thinking, first-principles reasoning, and the ability to
connect seemingly unrelated signals into a coherent risk thesis.

You operate against a live macro-financial monitoring framework (v3.2) tracking
a split hazard model: Market Convergence (correlated drawdown, gates, forced
selling) and Systemic Crisis (loss-absorption failure at sovereign or banking
core). The framework scores TEN signal cards on 0–3 tier scoring, weights two
correlation clusters (Hormuz factor = energy + fertilizer; AI-credit factor =
private_credit + ai_nexus), applies monotone escalator ratchets, and credits
pre-registered falsifiers. Systemic Crisis regime triggers at effective count
≥ 5.5 with policy-constrained factor.

PORTFOLIO (flag direct/indirect exposure):
US Growth Tech: MSFT, BIDU (China ADR), GRAB (SE Asia super-app), PONY AI
  (autonomous driving), COUR (EdTech), ADBE
US Energy: OXY, DVN (oil & gas), AES Corp (utilities/renewables)
US Defense & Insurance: BAH (Booz Allen Hamilton), ACGL, CNC
US Pharma: BMY, MRK
US Thematic ETFs: ICLN (clean energy), KARS (EVs), EIDO (Indonesia), IAUM (gold)
Singapore (SGX): DBS, UOB (banks); Raffles Medical, ParkwayLife REIT
  (healthcare); Wilmar International (agribusiness); Sembcorp (utilities/
  clean energy); CapitaLand Ascott Trust (hospitality REIT)
Malaysia: SP Setia (property developer)
Japan: Toyota (auto, two ticker classes)
Hong Kong: Pony AI Class A, Trip.com

SIGNAL-TO-HOLDINGS MAP:
fertilizer/food → Wilmar; JGB snapback → Toyota; AI-credit nexus → MSFT/ADBE/BIDU/PONY;
energy → OXY/DVN; us_equity_excess → full US book; ust_rollover → USD cash;
private_credit → DBS/UOB (fund-finance books)

RESEARCH SOURCES — prioritise in order:
1. Government/multilateral: BIS, IMF, Fed/ECB/MAS/BoJ speeches, WHO, IAEA,
   USDA, IEA, FSB, Japan MoF, FINRA margin debt
2. Independent analysts: Doomberg, Chartbook, Net Interest, The Overshoot,
   Kyla Scanlon, Cassandra Unchained
3. Cross-geography: Caixin, SCMP, Nikkei Asia, Straits Times, Al-Monitor, Kyodo
4. Primary data: Baltic Dry, Freightos, CDS levels, commodity futures, yield
   curves, TreasuryDirect auction results, FRED, CME FedWatch

MANUAL FIELDS — AUTO-APPLIED (apply when you have high-confidence fresh data):
  fed_cuts_priced_2026, kr_industrial_power_yoy_pct, oracle_cds_5y_bps,
  pik_rising_quarters, cape_manual (only if fetch_status.cape is failing)

PROPOSED-FOR-REVIEW (interpretive — propose but do not apply):
  taiwan_tier_manual, sea_policy_tier_manual, hyperscaler_guidance_cuts,
  redemption_gates_count, hormuz_closed_since, all four falsifier booleans

FALSIFIERS:
  ceasefire_and_reopening       −15 MC pts  (Hormuz blockade ends)
  hyperscaler_two_quarters_held  −8 MC pts  (Big-5 hold capex 2+ qtrs)
  true_defaults_rolling_over     −8 MC pts  (Fitch default rate declining)
  jgb_auctions_normalized        −5 MC pts  (BoJ YCC removed, bid-to-cover ≥2.5)

OUTPUT: Return ONLY valid JSON matching the schema provided. Use web search
broadly to gather current data. Cite sources inline as {name, url} objects.
Do not sensationalise. Distinguish signal from noise. Flag conflicting accounts.
Analytical framework output, not personalised investment advice."""

# --------------------------------------------------------------------------- #
#  JSON schema for structured analysis output                                  #
# --------------------------------------------------------------------------- #
ANALYSIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["thesis", "signals", "unknown_unknown", "undercurrent",
                 "framework_updates", "pandemic_tier", "pandemic_assessment",
                 "equity_commentary", "data_freshness_flags"],
    "properties": {
        "thesis": {"type": "string",
                   "description": "Part 1 — 3-5 sentence opinionated macro narrative."},
        "signals": {
            "type": "array",
            "description": "Part 2 — significant findings, one object per signal.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["domain", "card", "severity", "sources", "signal",
                             "why_matters", "portfolio_exposure", "framework_implication"],
                "properties": {
                    "domain":                {"type": "string"},
                    "card":                  {"type": "string"},
                    "severity":              {"type": "string",
                                             "enum": ["monitoring", "elevated", "critical"]},
                    "sources": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["name", "url"],
                            "properties": {
                                "name": {"type": "string"},
                                "url":  {"type": "string"}
                            }
                        }
                    },
                    "signal":                {"type": "string"},
                    "why_matters":           {"type": "string"},
                    "portfolio_exposure":    {"type": "string"},
                    "framework_implication": {"type": "string"}
                }
            }
        },
        "unknown_unknown": {
            "type": "string",
            "description": "Part 3 — one weak signal/structural tension nobody is talking about."
        },
        "undercurrent": {
            "type": "string",
            "description": "Part 4 — single sentence: the most underpriced risk today and why."
        },
        "framework_updates": {
            "type": "object",
            "additionalProperties": False,
            "required": ["auto_applied", "proposed", "not_updated", "recompute_note"],
            "properties": {
                "auto_applied": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["field", "from_val", "to_val", "basis", "confidence"],
                        "properties": {
                            "field":      {"type": "string"},
                            "from_val":   {"type": "string"},
                            "to_val":     {"type": "string"},
                            "basis":      {"type": "string"},
                            "confidence": {"type": "string", "enum": ["high"]}
                        }
                    }
                },
                "proposed": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["field", "from_val", "to_val", "basis", "confidence"],
                        "properties": {
                            "field":      {"type": "string"},
                            "from_val":   {"type": "string"},
                            "to_val":     {"type": "string"},
                            "basis":      {"type": "string"},
                            "confidence": {"type": "string",
                                          "enum": ["high", "medium", "low"]}
                        }
                    }
                },
                "not_updated":   {"type": "array", "items": {"type": "string"}},
                "recompute_note": {
                    "type": "string",
                    "description": "Summary of net change after applying auto updates."
                }
            }
        },
        "pandemic_tier": {
            "type": "integer",
            "description": "Part 6 — pandemic_tier_manual value (0-3)."
        },
        "pandemic_assessment": {
            "type": "string",
            "description": "Part 6 — WHO check: PHEIC status, cross-border, respiratory clustering, reasoning."
        },
        "equity_commentary": {
            "type": "string",
            "description": "Part 7 — US equity excess context: leverage narrative, CAPE driver, historical rhyme."
        },
        "data_freshness_flags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Any fetch_status failures or stale fields noticed in daily_readings.json."
        }
    }
}


# --------------------------------------------------------------------------- #
#  API call with agentic web-search loop                                       #
# --------------------------------------------------------------------------- #
def run_analysis(client: anthropic.Anthropic, state: dict, today: str) -> dict:
    """Call Claude with web_search, return parsed analysis dict."""
    computed = state.get("computed", {})
    manual   = state.get("manual", {})
    fals     = state.get("falsifiers", {})
    fstatus  = state.get("fetch_status", {})

    user_msg = (
        f"Today is {today} (Saturday — weekly Black Swan scan).\n\n"
        f"CURRENT FRAMEWORK STATE:\n```json\n"
        f"{json.dumps({'computed': computed, 'manual': manual, 'falsifiers': fals, 'fetch_status': fstatus}, indent=2)}\n```\n\n"
        "Perform the full 7-part analysis. Use web_search broadly across all risk domains. "
        "Return the result as JSON matching the schema exactly."
    )

    messages = [{"role": "user", "content": user_msg}]
    # web_search_20260209 is the current variant for Opus 5 / Sonnet 5
    tools = [{"type": "web_search_20260209", "name": "web_search",
              "max_uses": 20}]

    log.info("Calling %s for weekly analysis (web_search enabled)…", MODEL)
    iterations = 0
    while iterations < 30:
        iterations += 1
        with client.messages.stream(
            model=MODEL,
            max_tokens=64000,   # thinking + up to 20 web searches + full 7-part JSON (32000 truncated; streaming, so safe)
            system=SYSTEM,
            tools=tools,
            output_config={
                "effort": "high",
                "format": {"type": "json_schema", "schema": ANALYSIS_SCHEMA},
            },
            messages=messages,
        ) as stream:
            resp = stream.get_final_message()
        log.info("stop_reason=%s  content_types=%s",
                 resp.stop_reason,
                 [b.type for b in resp.content])

        if resp.stop_reason == "end_turn":
            text = next((b.text for b in resp.content if b.type == "text"), None)
            if text:
                return json.loads(text)
            raise RuntimeError("end_turn but no text block")

        if resp.stop_reason == "max_tokens":
            # Truncated output — fail loudly rather than returning broken JSON
            raise RuntimeError(
                "max_tokens hit after %d iterations — increase max_tokens or shorten schema" % iterations)

        if resp.stop_reason == "pause_turn":
            # Server-side tool (web_search) turn paused mid-way: resume by echoing the
            # assistant turn back unchanged.  (Previously fell through to "unexpected" and aborted.)
            messages.append({"role": "assistant", "content": resp.content})
            continue

        if resp.stop_reason == "tool_use":
            # Append assistant turn, then provide tool results so model can continue
            messages.append({"role": "assistant", "content": resp.content})
            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            if tool_uses:
                results = [
                    {"type": "tool_result", "tool_use_id": b.id,
                     "content": "Search executed by Anthropic infrastructure."}
                    for b in tool_uses
                ]
                messages.append({"role": "user", "content": results})
            else:
                # tool_use stop but no tool blocks — shouldn't happen, bail
                text = next((b.text for b in resp.content if b.type == "text"), None)
                if text:
                    return json.loads(text)
                break
        else:
            log.warning("Unexpected stop_reason: %s", resp.stop_reason)
            break

    raise RuntimeError("Analysis loop did not produce a result after %d iterations" % iterations)


# --------------------------------------------------------------------------- #
#  Apply auto-updates to daily_readings.json                                   #
# --------------------------------------------------------------------------- #
def apply_auto_updates(state: dict, updates: list[dict]) -> dict:
    """Write auto-applied numerical refreshes into state['manual']."""
    m = state.setdefault("manual", {})
    for u in updates:
        field = u["field"]
        old = m.get(field)
        try:
            # Try numeric conversion first
            val: object = float(u["to_val"])
            if val == int(val):
                val = int(val)
        except (ValueError, TypeError):
            val = u["to_val"]
        m[field] = val
        log.info("AUTO-APPLIED %s: %s → %s", field, old, val)
    return state


# --------------------------------------------------------------------------- #
#  Dashboard HTML renderer                                                     #
# --------------------------------------------------------------------------- #
SEVERITY_ICON = {"monitoring": "🟡", "elevated": "🟠", "critical": "🔴"}
SEVERITY_CLS  = {"monitoring": "t1",  "elevated": "t2",  "critical": "t3"}
TIER_CLS = {0: "t0", 1: "t1", 2: "t2", 3: "t3"}
TIER_LABEL = {0: "Contained", 1: "Watching", 2: "Elevated", 3: "Critical"}
CARD_NAMES = {
    "energy":         "Energy / Hormuz",
    "ust_rollover":   "UST Rollover",
    "jgb_snapback":   "JGB Snapback",
    "private_credit": "Private Credit",
    "ai_nexus":       "AI Nexus",
    "us_equity_excess": "US Equity Excess",
    "taiwan":         "Taiwan",
    "sea_policy":     "SEA Policy",
    "pandemic":       "Pandemic",
    "fertilizer":     "Fertilizer / Food",
}
CARD_DOMAIN = {
    "energy":           "Energy & Commodities",
    "ust_rollover":     "Financial Fragility",
    "jgb_snapback":     "Financial Fragility",
    "private_credit":   "Hidden Leverage",
    "ai_nexus":         "AI & Cyber",
    "us_equity_excess": "Financial Fragility",
    "taiwan":           "Geopolitical",
    "sea_policy":       "EM / SEA Policy",
    "pandemic":         "Pandemic & Biosecurity",
    "fertilizer":       "Energy & Commodities",
}
FALSIFIER_META = {
    "ceasefire_and_reopening":       ("Hormuz Ceasefire & Reopening", "−15 MC pts"),
    "hyperscaler_two_quarters_held": ("Hyperscaler Capex Held ≥2 Qtrs", "−8 MC pts"),
    "true_defaults_rolling_over":    ("True Default Rate Declining",   "−8 MC pts"),
    "jgb_auctions_normalized":       ("JGB Auctions Normalized",       "−5 MC pts"),
}
REGIME_COLORS = {
    "SYSTEMIC CRISIS":    ("#E0524E", "#3d1210"),
    "MARKET CONVERGENCE": ("#E08641", "#3d2010"),
    "COUPLING":           ("#E0B341", "#3d2f10"),
    "CONTAINED":          ("#3FB68B", "#0d2a1e"),
}


def esc(s) -> str:
    return html_mod.escape(str(s))


def _signal_card(sig: dict) -> str:
    sev    = sig.get("severity", "monitoring")
    cls    = SEVERITY_CLS.get(sev, "t1")
    icon   = SEVERITY_ICON.get(sev, "🟡")
    domain = esc(sig.get("domain", ""))
    card   = esc(sig.get("card", ""))
    sources_html = " ".join(
        f'<a href="{esc(s["url"])}" target="_blank">{esc(s["name"])}</a>'
        for s in sig.get("sources", [])[:4]
    )
    return f"""
<div class="sig-card tier-{cls}">
  <div class="sig-header">
    <span class="sig-domain">{domain}</span>
    <span class="sig-sev {cls}">{icon} {sev.capitalize()}</span>
  </div>
  <div class="sig-card-label">Card: <code>{card}</code></div>
  <p class="sig-signal"><strong>Signal:</strong> {esc(sig.get('signal',''))}</p>
  <p class="sig-why"><strong>Why it matters:</strong> {esc(sig.get('why_matters',''))}</p>
  <p class="sig-port"><strong>Portfolio:</strong> {esc(sig.get('portfolio_exposure',''))}</p>
  <p class="sig-impl"><strong>Framework:</strong> {esc(sig.get('framework_implication',''))}</p>
  {f'<div class="sig-sources">Sources: {sources_html}</div>' if sources_html else ''}
</div>"""


def _update_block(u: dict, kind: str) -> str:
    conf_cls = {"high": "t0", "medium": "t1", "low": "t2"}.get(
        u.get("confidence", "medium"), "t1")
    return f"""
<div class="update-block {kind}">
  <div class="update-header">
    <span class="update-kind {'applied' if kind=='auto' else 'proposed'}">{
      'AUTO-APPLIED' if kind == 'auto' else 'PROPOSED'}</span>
    <code class="update-field">{esc(u['field'])}</code>
    <span class="conf {conf_cls}">{esc(u.get('confidence',''))}</span>
  </div>
  <div class="update-diff">
    <span class="from-val">FROM: {esc(u.get('from_val','—'))}</span>
    <span class="arrow">→</span>
    <span class="to-val">TO: {esc(u.get('to_val','—'))}</span>
  </div>
  <p class="update-basis">{esc(u.get('basis',''))}</p>
</div>"""


def render_dashboard(state: dict, analysis: dict, today: str,
                     prev_dates: list[str]) -> str:
    c = state.get("computed", {})
    m = state.get("manual", {})
    f = state.get("falsifiers", {})
    fstatus = state.get("fetch_status", {})
    tiers = c.get("tiers", {})

    regime = c.get("regime", "UNKNOWN")
    mc     = c.get("mc_hazard", 0)
    sc     = c.get("sc_hazard", 0)
    eff    = c.get("effective_count", 0.0)
    hormuz = c.get("hormuz_months", 0.0)
    esc_pts= c.get("escalator_pts", 0.0)
    fc     = c.get("falsifier_credit", 0)
    cont   = c.get("containment_factor", 0.45)
    asof   = state.get("as_of", "")

    reg_color, reg_bg = REGIME_COLORS.get(regime, ("#8597A4", "#1A2730"))
    stale_days = ""
    if asof:
        try:
            delta = (dt.date.today() - dt.date.fromisoformat(asof[:10])).days
            stale_days = f"{delta}d ago"
        except Exception:
            stale_days = asof[:10]

    # --- signal cards ---
    signal_cards_html = "\n".join(_signal_card(s) for s in analysis.get("signals", []))

    # --- framework cards ---
    fw_cards_html = ""
    for key in ["energy", "ust_rollover", "jgb_snapback", "private_credit",
                 "ai_nexus", "us_equity_excess", "taiwan", "sea_policy",
                 "pandemic", "fertilizer"]:
        tier = tiers.get(key)
        if tier is None:
            tier = 0
        t_cls = TIER_CLS.get(tier, "t1")
        fw_cards_html += f"""
<div class="fw-card tier-{t_cls}">
  <div class="fw-top">
    <span class="fw-name">{esc(CARD_NAMES.get(key, key))}</span>
    <span class="fw-tier {t_cls}">T{tier}</span>
  </div>
  <div class="fw-sub">{esc(CARD_DOMAIN.get(key,''))}</div>
  <div class="fw-bar-wrap"><div class="fw-bar {t_cls}" style="width:{min(tier*34,100)}%"></div></div>
  <div class="fw-tier-label">{esc(TIER_LABEL.get(tier,''))}</div>
</div>"""

    # --- falsifiers ---
    fals_html = ""
    for key, (name, credit) in FALSIFIER_META.items():
        active = f.get(key, False)
        fals_html += f"""
<div class="fal{'  fal-active' if active else ''}">
  <div class="fal-header">
    <span class="fal-name">{esc(name)}</span>
    <span class="fal-credit">{esc(credit)}</span>
    <span class="fal-state {'on' if active else ''}">{'ACTIVE' if active else 'WATCHING'}</span>
  </div>
</div>"""

    # --- framework updates ---
    auto_html = "".join(_update_block(u, "auto")
                        for u in analysis.get("framework_updates", {}).get("auto_applied", []))
    prop_html = "".join(_update_block(u, "prop")
                        for u in analysis.get("framework_updates", {}).get("proposed", []))
    not_upd_html = ""
    for item in analysis.get("framework_updates", {}).get("not_updated", []):
        not_upd_html += f'<li>{esc(item)}</li>'

    # --- fetch status ---
    fstatus_html = ""
    for src, st in fstatus.items():
        cls = "fstatus-ok" if st.startswith("ok") else "fstatus-warn"
        fstatus_html += f'<div class="{cls}"><code>{esc(src)}</code>: {esc(st)}</div>'

    # --- freshness flags (computed live from state, not from stale analysis JSON) ---
    live_flags: list[str] = []
    # as_of staleness
    if asof:
        try:
            _delta = (dt.date.today() - dt.date.fromisoformat(asof[:10])).days
            if _delta > 2:
                live_flags.append(
                    f"daily_readings.json as_of is {asof[:10]} — auto block {_delta}d stale")
        except Exception:
            pass
    # fetch_status failures / parse-empty
    for _src, _st in fstatus.items():
        if not _st.startswith("ok"):
            live_flags.append(f"{_src}: {_st}")
    # margin_debt_asof: flag if older than 60 days
    _md_asof = state.get("auto", {}).get("margin_debt_asof", "")
    if _md_asof:
        try:
            _md_delta = (dt.date.today() - dt.date.fromisoformat(_md_asof[:10])).days
            if _md_delta > 60:
                live_flags.append(
                    f"auto.margin_debt_asof is {_md_asof[:10]} — margin series {_md_delta}d stale")
        except Exception:
            pass
    # jgb_date: flag if not a date-like string
    import re as _re
    _jgb = state.get("auto", {}).get("jgb_date", "")
    if _jgb and not _re.match(r'^\d{4}/\d{1,2}/\d{1,2}$', _jgb.strip()):
        live_flags.append(f"auto.jgb_date holds non-date value: {_jgb[:60]}")
    flags_html = ""
    for flag in live_flags:
        flags_html += f'<div class="freshflag">⚠ {esc(flag)}</div>'

    # --- history links ---
    history_html = ""
    for d in sorted(prev_dates, reverse=True)[:12]:
        history_html += f'<a href="watch_{esc(d)}.json" class="hist-link">{esc(d)}</a>'

    mc_bar = min(mc, 100)
    sc_bar = min(sc, 100)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Black Swan v3.2 — {esc(today)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{{
  --ink:#0D1318; --panel:#141E26; --panel2:#1A2730; --line:#26343F;
  --text:#E8EEF2; --muted:#8597A4; --faint:#5C6F7C;
  --phosphor:#5FD4E0;
  --t0:#3FB68B; --t0-dim:rgba(63,182,139,.14); --t0-mid:rgba(63,182,139,.3);
  --t1:#E0B341; --t1-dim:rgba(224,179,65,.14);  --t1-mid:rgba(224,179,65,.3);
  --t2:#E08641; --t2-dim:rgba(224,134,65,.14);  --t2-mid:rgba(224,134,65,.3);
  --t3:#E0524E; --t3-dim:rgba(224,82,78,.14);   --t3-mid:rgba(224,82,78,.3);
  --sc-col:#C77DE0;
  --r:10px;
}}
*{{box-sizing:border-box;margin:0;padding:0;}}
html,body{{background:var(--ink);color:var(--text);font-family:'Inter',system-ui,sans-serif;
  -webkit-font-smoothing:antialiased;}}
a{{color:var(--phosphor);text-decoration:none;}} a:hover{{text-decoration:underline;}}
.wrap{{max-width:1200px;margin:0 auto;padding:28px 20px 80px;}}
.mono{{font-family:'JetBrains Mono',monospace;}}
.disp{{font-family:'Space Grotesk',sans-serif;}}
code{{font-family:'JetBrains Mono',monospace;font-size:.85em;background:var(--panel2);
  padding:1px 5px;border-radius:4px;}}

/* ---- HEADER ---- */
.header{{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;
  gap:14px;border-bottom:1px solid var(--line);padding-bottom:18px;margin-bottom:24px;}}
.header h1{{font-family:'Space Grotesk';font-size:22px;font-weight:700;}}
.header h1 .v{{color:var(--phosphor);}}
.header-sub{{font-size:12px;color:var(--muted);margin-top:4px;}}
.asof{{text-align:right;font-size:12px;color:var(--muted);}}

/* ---- REGIME HERO ---- */
.hero{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:24px;}}
@media(max-width:800px){{.hero{{grid-template-columns:1fr;}}}}
.hero-card{{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:20px;}}
.regime-chip{{display:inline-block;font-family:'JetBrains Mono';font-weight:700;font-size:13px;
  letter-spacing:1.4px;padding:8px 18px;border-radius:999px;border:2px solid {esc(reg_color)};
  color:{esc(reg_color)};background:{esc(reg_bg)};margin-bottom:14px;}}
.hazard-row{{margin-bottom:12px;}}
.hazard-label{{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);
  margin-bottom:5px;}}
.hazard-label .num{{font-family:'JetBrains Mono';font-size:20px;font-weight:700;}}
.hazard-label .num.mc{{color:var(--phosphor);}} .hazard-label .num.sc{{color:var(--sc-col);}}
.bar-track{{height:8px;background:var(--panel2);border-radius:4px;overflow:hidden;}}
.bar-fill{{height:100%;border-radius:4px;transition:width .4s;}}
.bar-mc{{background:var(--phosphor);}}
.bar-sc{{background:var(--sc-col);}}

.mech-row{{display:flex;justify-content:space-between;align-items:baseline;
  padding:7px 0;border-bottom:1px dashed var(--line);font-size:13px;}}
.mech-row:last-child{{border-bottom:none;}}
.mech-k{{color:var(--muted);}} .mech-v{{font-family:'JetBrains Mono';font-weight:700;}}
.mech-v.plus{{color:var(--t2);}} .mech-v.minus{{color:var(--t0);}}

/* ---- TABS ---- */
.tabs{{display:flex;gap:4px;border-bottom:2px solid var(--line);margin-bottom:24px;overflow-x:auto;}}
.tab-btn{{padding:9px 18px;font-size:13px;font-weight:600;background:none;border:none;
  color:var(--muted);cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-2px;
  font-family:'Inter',sans-serif;white-space:nowrap;}}
.tab-btn:hover{{color:var(--text);}}
.tab-btn.active{{color:var(--phosphor);border-bottom-color:var(--phosphor);}}
.tab-pane{{display:none;}} .tab-pane.active{{display:block;}}

/* ---- FRAMEWORK CARDS ---- */
.fw-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;margin-bottom:24px;}}
.fw-card{{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);
  padding:14px;border-left:4px solid var(--line);}}
.fw-card.tier-t0{{border-left-color:var(--t0);}}
.fw-card.tier-t1{{border-left-color:var(--t1);}}
.fw-card.tier-t2{{border-left-color:var(--t2);}}
.fw-card.tier-t3{{border-left-color:var(--t3);}}
.fw-top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;}}
.fw-name{{font-weight:600;font-size:13px;}}
.fw-tier{{font-family:'JetBrains Mono';font-size:11px;font-weight:700;padding:2px 8px;
  border-radius:999px;}}
.fw-tier.t0{{color:var(--t0);background:var(--t0-dim);}}.fw-tier.t1{{color:var(--t1);background:var(--t1-dim);}}
.fw-tier.t2{{color:var(--t2);background:var(--t2-dim);}}.fw-tier.t3{{color:var(--t3);background:var(--t3-dim);}}
.fw-sub{{font-size:11px;color:var(--faint);margin-bottom:8px;}}
.fw-bar-wrap{{height:5px;background:var(--panel2);border-radius:3px;overflow:hidden;margin-bottom:5px;}}
.fw-bar{{height:100%;border-radius:3px;}}
.fw-bar.t0{{background:var(--t0);}}.fw-bar.t1{{background:var(--t1);}}
.fw-bar.t2{{background:var(--t2);}}.fw-bar.t3{{background:var(--t3);}}
.fw-tier-label{{font-size:10px;color:var(--faint);text-transform:uppercase;letter-spacing:.8px;}}

/* ---- FALSIFIERS ---- */
.fal-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;margin-bottom:24px;}}
.fal{{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:14px;}}
.fal-active{{border-color:var(--t0-mid);}}
.fal-header{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;}}
.fal-name{{font-weight:600;font-size:12.5px;flex:1;}}
.fal-credit{{font-family:'JetBrains Mono';font-size:11px;color:var(--faint);}}
.fal-state{{font-family:'JetBrains Mono';font-size:10px;letter-spacing:1px;padding:3px 8px;
  border-radius:999px;border:1px solid var(--line);color:var(--faint);}}
.fal-state.on{{color:var(--t0);border-color:var(--t0);background:var(--t0-dim);}}

/* ---- SIGNAL LOG ---- */
.sig-grid{{display:flex;flex-direction:column;gap:14px;}}
.sig-card{{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);
  padding:16px;border-left:4px solid var(--line);}}
.sig-card.tier-t1{{border-left-color:var(--t1);}}.sig-card.tier-t2{{border-left-color:var(--t2);}}
.sig-card.tier-t3{{border-left-color:var(--t3);}}
.sig-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;}}
.sig-domain{{font-weight:600;font-size:13.5px;}}
.sig-sev{{font-family:'JetBrains Mono';font-size:11px;font-weight:700;padding:3px 10px;
  border-radius:999px;}}
.sig-sev.t1{{color:var(--t1);background:var(--t1-dim);}}.sig-sev.t2{{color:var(--t2);background:var(--t2-dim);}}
.sig-sev.t3{{color:var(--t3);background:var(--t3-dim);}}
.sig-card-label{{font-size:11px;color:var(--faint);margin-bottom:8px;}}
.sig-signal,.sig-why,.sig-port,.sig-impl{{font-size:13px;color:var(--text);margin-bottom:6px;line-height:1.55;}}
.sig-sources{{font-size:11.5px;color:var(--faint);margin-top:8px;border-top:1px solid var(--line);
  padding-top:6px;}}
.sig-sources a{{color:var(--phosphor);margin-right:8px;}}

/* ---- THESIS / PROSE BOXES ---- */
.prose-box{{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);
  padding:20px;margin-bottom:16px;}}
.prose-box h3{{font-family:'Space Grotesk';font-size:14px;font-weight:700;color:var(--phosphor);
  margin-bottom:10px;letter-spacing:.3px;}}
.prose-box p{{font-size:13.5px;line-height:1.7;color:var(--text);}}
.undercurrent-box{{background:var(--panel2);border:1px solid {esc(reg_color)};border-radius:var(--r);
  padding:16px 20px;margin-bottom:16px;}}
.undercurrent-box p{{font-size:14px;font-style:italic;line-height:1.6;color:var(--text);}}

/* ---- FRAMEWORK UPDATES ---- */
.update-block{{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);
  padding:14px;margin-bottom:10px;}}
.update-block.auto{{border-left:4px solid var(--t0);}}
.update-block.prop{{border-left:4px solid var(--t1);}}
.update-header{{display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap;}}
.update-kind{{font-family:'JetBrains Mono';font-size:10px;font-weight:700;letter-spacing:1.2px;
  padding:3px 8px;border-radius:999px;}}
.update-kind.applied{{color:var(--t0);background:var(--t0-dim);}}
.update-kind.proposed{{color:var(--t1);background:var(--t1-dim);}}
.update-field{{font-size:12px;font-weight:700;flex:1;}}
.conf.t0{{color:var(--t0);}}.conf.t1{{color:var(--t1);}}.conf.t2{{color:var(--t2);}}
.conf{{font-size:11px;font-family:'JetBrains Mono';}}
.update-diff{{display:flex;align-items:center;gap:10px;margin-bottom:6px;font-size:12px;
  font-family:'JetBrains Mono';}}
.from-val{{color:var(--faint);}}.arrow{{color:var(--muted);}}.to-val{{color:var(--text);font-weight:600;}}
.update-basis{{font-size:12px;color:var(--muted);line-height:1.5;}}

/* ---- FETCH STATUS / FLAGS ---- */
.fstatus-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:8px;margin-bottom:16px;}}
.fstatus-ok,.fstatus-warn{{padding:6px 10px;border-radius:6px;font-size:11.5px;}}
.fstatus-ok{{background:var(--t0-dim);color:var(--t0);}}.fstatus-warn{{background:var(--t3-dim);color:var(--t3);}}
.freshflag{{background:var(--t1-dim);color:var(--t1);border-radius:6px;padding:7px 12px;
  font-size:12px;margin-bottom:6px;}}

/* ---- PORTFOLIO TABLE ---- */
.port-table{{width:100%;border-collapse:collapse;font-size:12.5px;}}
.port-table th{{font-weight:600;color:var(--muted);text-align:left;padding:8px 10px;
  border-bottom:1px solid var(--line);font-size:11px;letter-spacing:.5px;text-transform:uppercase;}}
.port-table td{{padding:8px 10px;border-bottom:1px dashed var(--line);vertical-align:top;}}
.port-table tr:last-child td{{border-bottom:none;}}
.port-table .card-tag{{display:inline-block;font-family:'JetBrains Mono';font-size:10px;
  padding:2px 6px;border-radius:4px;margin:1px;}}

/* ---- HISTORY ---- */
.hist-links{{display:flex;flex-wrap:wrap;gap:8px;}}
.hist-link{{font-family:'JetBrains Mono';font-size:12px;padding:5px 12px;border-radius:6px;
  background:var(--panel);border:1px solid var(--line);color:var(--muted);}}
.hist-link:hover{{color:var(--phosphor);border-color:var(--phosphor);}}

/* ---- SECTION HEADER ---- */
.sec-hdr{{font-family:'Space Grotesk';font-size:13px;font-weight:700;color:var(--faint);
  letter-spacing:1.5px;text-transform:uppercase;margin-bottom:14px;padding-bottom:6px;
  border-bottom:1px solid var(--line);}}
.sec-wrap{{margin-bottom:28px;}}

footer{{margin-top:40px;text-align:center;font-size:11px;color:var(--faint);}}
</style>
</head>
<body>
<div class="wrap">

<!-- HEADER -->
<div class="header">
  <div>
    <h1 class="disp">🦢 Black Swan <span class="v">v3.2</span></h1>
    <div class="header-sub">Split-Regime Hazard Monitor · Weekly analysis {esc(today)}</div>
  </div>
  <div class="asof">
    Data as-of <span class="mono">{esc(asof[:10] if asof else '—')}</span>
    {f' <span style="color:var(--t1)">({esc(stale_days)} stale)</span>' if stale_days else ''}
  </div>
</div>

<!-- HERO PANEL -->
<div class="hero">
  <!-- Regime chip + hazards -->
  <div class="hero-card" style="grid-column:span 2;">
    <div class="regime-chip">{esc(regime)}</div>
    <div class="hazard-row">
      <div class="hazard-label">
        <span>Market Convergence</span>
        <span class="num mc">{mc}%</span>
      </div>
      <div class="bar-track"><div class="bar-fill bar-mc" style="width:{mc_bar}%"></div></div>
    </div>
    <div class="hazard-row" style="margin-top:10px;">
      <div class="hazard-label">
        <span>Systemic Crisis</span>
        <span class="num sc">{sc}%</span>
      </div>
      <div class="bar-track"><div class="bar-fill bar-sc" style="width:{sc_bar}%"></div></div>
    </div>
  </div>
  <!-- Mechanics -->
  <div class="hero-card">
    <div class="mech-row"><span class="mech-k">Effective count</span>
      <span class="mech-v">{eff}</span></div>
    <div class="mech-row"><span class="mech-k">Hormuz (months)</span>
      <span class="mech-v plus">{hormuz:.1f}</span></div>
    <div class="mech-row"><span class="mech-k">Escalator pts</span>
      <span class="mech-v plus">+{esc_pts:.1f}</span></div>
    <div class="mech-row"><span class="mech-k">Falsifier credit</span>
      <span class="mech-v minus">{fc}</span></div>
    <div class="mech-row"><span class="mech-k">Containment factor</span>
      <span class="mech-v">{cont}</span></div>
  </div>
</div>

<!-- TABS -->
<div class="tabs">
  <button class="tab-btn active" onclick="switchTab('analysis')">Weekly Analysis</button>
  <button class="tab-btn" onclick="switchTab('framework')">Framework Cards</button>
  <button class="tab-btn" onclick="switchTab('portfolio')">Portfolio Exposure</button>
  <button class="tab-btn" onclick="switchTab('history')">History</button>
</div>

<!-- TAB: WEEKLY ANALYSIS -->
<div id="tab-analysis" class="tab-pane active">

  {f'<div class="sec-wrap">{flags_html}</div>' if flags_html else ''}

  <div class="sec-wrap">
    <div class="sec-hdr">Part 1 — Thesis</div>
    <div class="prose-box">
      <p>{esc(analysis.get('thesis',''))}</p>
    </div>
  </div>

  <div class="sec-wrap">
    <div class="sec-hdr">Part 2 — Signal Log</div>
    <div class="sig-grid">{signal_cards_html}</div>
  </div>

  <div class="sec-wrap">
    <div class="sec-hdr">Part 3 — Unknown Unknowns</div>
    <div class="prose-box">
      <h3>🔍 Slow-burning fuse</h3>
      <p>{esc(analysis.get('unknown_unknown',''))}</p>
    </div>
  </div>

  <div class="sec-wrap">
    <div class="sec-hdr">Part 4 — Undercurrent of the Day</div>
    <div class="undercurrent-box">
      <p>{esc(analysis.get('undercurrent',''))}</p>
    </div>
  </div>

  <div class="sec-wrap">
    <div class="sec-hdr">Part 5 — Framework Update</div>
    {'<div class="sec-hdr" style="font-size:11px;margin-bottom:8px;">AUTO-APPLIED</div>' + auto_html if auto_html else '<p style="font-size:13px;color:var(--muted);margin-bottom:16px;">No auto-applied updates this week.</p>'}
    {'<div class="sec-hdr" style="font-size:11px;margin-top:16px;margin-bottom:8px;">PROPOSED FOR REVIEW</div>' + prop_html if prop_html else ''}
    {f'<div class="sec-hdr" style="font-size:11px;margin-top:16px;margin-bottom:8px;">NOT UPDATED</div><ul style="color:var(--muted);font-size:12.5px;padding-left:20px;line-height:2;">{not_upd_html}</ul>' if not_upd_html else ''}
    {f'<div class="prose-box" style="margin-top:14px;"><h3>Recompute Note</h3><p>{esc(analysis.get("framework_updates",{}).get("recompute_note",""))}</p></div>' if analysis.get("framework_updates",{}).get("recompute_note") else ''}
  </div>

  <div class="sec-wrap">
    <div class="sec-hdr">Part 6 — Pandemic Signal Assessment</div>
    <div class="prose-box">
      <h3>Pandemic tier: <span style="color:var(--{'t0' if analysis.get('pandemic_tier',0)==0 else 't1' if analysis.get('pandemic_tier')==1 else 't2' if analysis.get('pandemic_tier')==2 else 't3'})">T{analysis.get('pandemic_tier',0)}</span></h3>
      <p style="margin-top:8px;">{esc(analysis.get('pandemic_assessment',''))}</p>
    </div>
  </div>

  <div class="sec-wrap">
    <div class="sec-hdr">Part 7 — US Equity Excess Commentary</div>
    <div class="prose-box">
      <p>{esc(analysis.get('equity_commentary',''))}</p>
    </div>
  </div>

</div>

<!-- TAB: FRAMEWORK CARDS -->
<div id="tab-framework" class="tab-pane">
  <div class="sec-wrap">
    <div class="sec-hdr">Signal Cards</div>
    <div class="fw-grid">{fw_cards_html}</div>
  </div>
  <div class="sec-wrap">
    <div class="sec-hdr">Falsifiers</div>
    <div class="fal-grid">{fals_html}</div>
  </div>
  <div class="sec-wrap">
    <div class="sec-hdr">Data Fetch Status</div>
    <div class="fstatus-grid">{fstatus_html}</div>
  </div>
</div>

<!-- TAB: PORTFOLIO EXPOSURE -->
<div id="tab-portfolio" class="tab-pane">
  <div class="sec-wrap">
    <div class="sec-hdr">Holdings × Signal Card Map</div>
    <table class="port-table">
      <thead><tr><th>Holding</th><th>Market</th><th>Signal Cards</th><th>Exposure Notes</th></tr></thead>
      <tbody>
        <tr><td><strong>OXY, DVN</strong></td><td>US</td><td>
          <span class="card-tag" style="background:var(--t3-dim);color:var(--t3)">energy</span></td>
          <td>Direct oil price exposure; DVN CEO insider BUY signal current</td></tr>
        <tr><td><strong>MSFT, ADBE</strong></td><td>US</td><td>
          <span class="card-tag" style="background:var(--t1-dim);color:var(--t1)">ai_nexus</span>
          <span class="card-tag" style="background:var(--t3-dim);color:var(--t3)">us_equity_excess</span></td>
          <td>AI capex narrative; high-multiple duration risk</td></tr>
        <tr><td><strong>BIDU, PONY AI</strong></td><td>US/HK</td><td>
          <span class="card-tag" style="background:var(--t1-dim);color:var(--t1)">ai_nexus</span>
          <span class="card-tag" style="background:var(--t1-dim);color:var(--t1)">taiwan</span></td>
          <td>China ADR; AI-credit cluster + geopolitical beta</td></tr>
        <tr><td><strong>GRAB</strong></td><td>US</td><td>
          <span class="card-tag" style="background:var(--t1-dim);color:var(--t1)">sea_policy</span></td>
          <td>SE Asia revenue; BI rupiah defence risk; COO cluster sell signal</td></tr>
        <tr><td><strong>Wilmar</strong></td><td>SGX</td><td>
          <span class="card-tag" style="background:var(--t1-dim);color:var(--t1)">fertilizer</span>
          <span class="card-tag" style="background:var(--t3-dim);color:var(--t3)">energy</span></td>
          <td>Agribusiness — freight/fertilizer input costs; Hormuz-linked</td></tr>
        <tr><td><strong>DBS, UOB</strong></td><td>SGX</td><td>
          <span class="card-tag" style="background:var(--t2-dim);color:var(--t2)">private_credit</span>
          <span class="card-tag" style="background:var(--t3-dim);color:var(--t3)">ust_rollover</span></td>
          <td>Fund-finance / NAV lending; duration re-pricing</td></tr>
        <tr><td><strong>ParkwayLife REIT, CapitaLand Ascott</strong></td><td>SGX</td><td>
          <span class="card-tag" style="background:var(--t3-dim);color:var(--t3)">ust_rollover</span></td>
          <td>REIT duration; SGD rates track USD higher</td></tr>
        <tr><td><strong>Toyota</strong></td><td>TSE</td><td>
          <span class="card-tag" style="background:var(--t2-dim);color:var(--t2)">jgb_snapback</span>
          <span class="card-tag" style="background:var(--t3-dim);color:var(--t3)">energy</span></td>
          <td>Yen-sensitive; Japan energy import bill; BoJ 1.25% — near 162 ratchet</td></tr>
        <tr><td><strong>SP Setia</strong></td><td>Bursa</td><td>
          <span class="card-tag" style="background:var(--t3-dim);color:var(--t3)">ust_rollover</span></td>
          <td>Leveraged developer; MYR rate sensitivity</td></tr>
        <tr><td><strong>COUR, KARS, ICLN</strong></td><td>US</td><td>
          <span class="card-tag" style="background:var(--t3-dim);color:var(--t3)">us_equity_excess</span></td>
          <td>High-multiple thematic; most exposed to valuation-correction scenario</td></tr>
        <tr><td><strong>BMY, MRK, BAH, ACGL, CNC</strong></td><td>US</td><td>
          <span class="card-tag" style="background:var(--t0-dim);color:var(--t0)">defensive</span></td>
          <td>Partial offsets to valuation/leverage-unwind risk</td></tr>
        <tr><td><strong>IAUM (gold)</strong></td><td>US</td><td>
          <span class="card-tag" style="background:var(--t0-dim);color:var(--t0)">safe-haven</span></td>
          <td>Hedge against Systemic Crisis scenario</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- TAB: HISTORY -->
<div id="tab-history" class="tab-pane">
  <div class="sec-wrap">
    <div class="sec-hdr">Previous Weekly Analyses</div>
    <div class="hist-links">{history_html}</div>
    <p style="margin-top:16px;font-size:12px;color:var(--faint);">
      JSON files are in the same directory. Open in Claude Code or any JSON viewer.
      The current week's full analysis is also saved as <code>watch_{esc(today)}.json</code>.
    </p>
  </div>
</div>

</div><!-- wrap -->

<footer>
  Black Swan v3.2 · Generated {esc(dt.datetime.now().strftime('%Y-%m-%d %H:%M SGT'))} ·
  Model: {esc(MODEL)} · Analytical output only, not investment advice.
</footer>

<script>
function switchTab(id) {{
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + id).classList.add('active');
  event.currentTarget.classList.add('active');
  try {{ localStorage.setItem('bswan_tab', id); }} catch(e) {{}}
}}
try {{
  const saved = localStorage.getItem('bswan_tab');
  if (saved) {{
    const btn = [...document.querySelectorAll('.tab-btn')].find(b =>
      b.getAttribute('onclick').includes("'" + saved + "'"));
    if (btn) btn.click();
  }}
}} catch(e) {{}}
</script>
</body>
</html>"""


# --------------------------------------------------------------------------- #
#  Main                                                                        #
# --------------------------------------------------------------------------- #
def _api_available(force_offline: bool) -> tuple[bool, str]:
    """(usable, reason-if-not).  Credentials are optional by design."""
    if force_offline or os.environ.get("BSWAN_OFFLINE") == "1":
        return False, "offline mode requested (--offline / BSWAN_OFFLINE=1)"
    if anthropic is None:
        return False, "anthropic SDK not installed"
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
            or os.path.isdir(os.path.expanduser("~/.config/anthropic"))):
        return False, "no API credentials set (the API is optional)"
    return True, ""


def _latest_watch() -> tuple[str | None, dict]:
    """Most recent readable watch_YYYY-MM-DD.json -> (date, analysis); (None, {}) if none."""
    for p in sorted(glob.glob(str(DIR / "watch_20*.json")), reverse=True):
        try:
            return Path(p).stem.replace("watch_", ""), json.loads(Path(p).read_text())
        except Exception as e:  # noqa: BLE001 — skip a corrupt file, try the next
            log.warning("skipping unreadable %s: %s", p, e)
    return None, {}


def _offline_banner(reason: str, analysis_date: str | None, state: dict) -> str:
    asof = str(state.get("as_of", "unknown"))[:16].replace("T", " ")
    if analysis_date:
        what = (f"Hazard numbers, tiers and falsifiers below are current as of <b>{esc(asof)}</b> "
                f"(daily_readings.json). The written analysis is from the <b>{esc(analysis_date)}</b> run "
                f"and was <b>not refreshed</b> this time.")
    else:
        what = (f"Hazard numbers, tiers and falsifiers are current as of <b>{esc(asof)}</b>; "
                f"no saved written analysis exists yet, so the narrative sections are empty.")
    return ('<div style="margin:12px auto;max-width:1200px;padding:10px 14px;border-radius:6px;'
            'border:1px solid rgba(255,170,0,.55);background:rgba(255,170,0,.12);color:inherit;'
            'font:13px/1.5 -apple-system,system-ui,sans-serif">'
            f'<b>Offline run</b> &mdash; {esc(reason)}. {what}</div>')


def _write_status(mode: str, reason: str, analysis_date: str | None):
    try:
        (DIR / "watcher_status.json").write_text(json.dumps({
            "ran_at": dt.datetime.now().isoformat(timespec="seconds"), "mode": mode,
            "reason": reason, "analysis_date": analysis_date, "model": MODEL if mode == "live" else None}, indent=2))
    except OSError as e:
        log.warning("could not write watcher_status.json: %s", e)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--dashboard-only", action="store_true",
                        help="Re-render dashboard from existing watch JSON without calling Claude")
    parser.add_argument("--offline", action="store_true",
                        help="Never call the API (also BSWAN_OFFLINE=1): render from current readings + last saved analysis")
    args = parser.parse_args()
    today = args.date

    if not READINGS.exists():
        log.error("daily_readings.json not found at %s", READINGS)
        sys.exit(1)

    state = json.loads(READINGS.read_text())
    watch_path = DIR / f"watch_{today}.json"

    # Previous watch dates for history tab
    prev_dates = sorted(
        Path(p).stem.replace("watch_", "")
        for p in glob.glob(str(DIR / "watch_20*.json"))
    )

    analysis: dict | None = None
    offline_reason = ""

    if args.dashboard_only:
        if watch_path.exists():
            analysis = json.loads(watch_path.read_text())
            log.info("Dashboard-only mode: rendering from %s", watch_path)
        else:
            offline_reason = f"--dashboard-only but no watch file for {today}"
    else:
        usable, why = _api_available(args.offline)
        if not usable:
            offline_reason = why
        else:
            try:
                # Pass workspace-id header when the key is org-scoped (not workspace-scoped).
                # Set ANTHROPIC_WORKSPACE_ID in ~/.config/insider-scan/env if needed.
                _ws_id = os.environ.get("ANTHROPIC_WORKSPACE_ID", "")
                _client_kwargs: dict = {}
                if _ws_id:
                    _client_kwargs["default_headers"] = {"anthropic-workspace-id": _ws_id}
                client = anthropic.Anthropic(**_client_kwargs)
                analysis = run_analysis(client, state, today)
                analysis["date"] = today
                analysis["model"] = MODEL
                analysis["generated_at"] = dt.datetime.now().isoformat()
                # Save the analysis FIRST so a problem applying updates can never lose it.
                watch_path.write_text(json.dumps(analysis, indent=2, ensure_ascii=False))
                log.info("Saved analysis -> %s", watch_path)
                try:
                    auto_updates = analysis.get("framework_updates", {}).get("auto_applied", [])
                    if auto_updates:
                        import shutil
                        bak = READINGS.with_suffix(".json.bak_watcher")
                        shutil.copy2(READINGS, bak)
                        state = apply_auto_updates(state, auto_updates)
                        READINGS.write_text(json.dumps(state, indent=2))
                        log.info("Wrote %d auto-updates to daily_readings.json (backup: %s)", len(auto_updates), bak)
                except Exception as e:  # noqa: BLE001
                    log.error("auto-updates NOT applied (analysis is saved): %s: %s", type(e).__name__, e)
            except Exception as e:  # noqa: BLE001 — any live failure degrades to an offline run
                analysis = None
                offline_reason = f"live analysis failed ({type(e).__name__}: {str(e)[:220]})"

    offline = analysis is None
    analysis_date: str | None = today
    if offline:
        analysis_date, analysis = _latest_watch()
        log.warning("OFFLINE RUN - analysis NOT refreshed: %s | rendering from current readings + %s",
                    offline_reason, f"analysis of {analysis_date}" if analysis_date else "no saved analysis")

    # In an offline run the header should name the narrative's date, not pretend it is fresh.
    html = render_dashboard(state, analysis, (analysis_date or today) if offline else today, prev_dates)
    if offline:
        banner = _offline_banner(offline_reason, analysis_date, state)
        html = html.replace("<body>", "<body>" + banner, 1) if "<body>" in html else banner + html
    DASHBOARD.write_text(html, encoding="utf-8")
    log.info("Dashboard -> %s", DASHBOARD)
    _write_status("offline" if offline else "live", offline_reason, analysis_date if offline else today)

    computed = state.get("computed", {})
    log.info("DONE (%s) - %s | MC %s%% | SC %s%% | eff %.1f",
             "OFFLINE" if offline else "live",
             computed.get("regime","?"),
             computed.get("mc_hazard","?"),
             computed.get("sc_hazard","?"),
             computed.get("effective_count",0.0))


if __name__ == "__main__":
    main()
