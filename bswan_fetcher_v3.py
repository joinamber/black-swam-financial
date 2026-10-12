#!/usr/bin/env python3
"""
bswan_fetcher_v3.py — Black Swan Daily Convergence Monitor, v3.4 data fetcher
============================================================================
v3.4 (30 Jul 2026): hardened market feed. Replaced the per-ticker yfinance
  burst with a single batched download, exponential backoff + jitter on HTTP
  429s, a shared browser-UA keep-alive session, and a keyless Stooq fallback
  for spot quotes and QQQ history. A single Yahoo rate-limit no longer zeroes
  every downstream commodity/FX field. Hazard model unchanged.

v3.2 (10 Jul 2026): one new signal card + automation of one manual field.
  * NEW CARD: us_equity_excess — combines FINRA/Fed margin debt YoY (via
    FRED BOGZ1FL663067003Q, quarterly) and Shiller CAPE (via multpl.com,
    scraped daily). Captures retail equity leverage + market-wide valuation
    stretch — a distinct dimension from the AI-credit cluster.
  * AUTOMATED: private credit true default rate now scraped from Fitch
    commentary on lsta.org. Manual field preserved as override; automation
    only writes when it finds a fresher print than what's already there.

Usage:
    FRED_API_KEY=xxxx python3 bswan_fetcher_v3.py
    (or put FRED_API_KEY=xxxx in a .env file next to this script)

Dependencies:  pip install requests yfinance
Output:        daily_readings.json  (same folder; manual fields preserved)
"""

import calendar
import csv
import io
import json
import os
import random
import re
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

try:
    import yfinance as yf
    HAVE_YF = True
except ImportError:
    HAVE_YF = False

# Shared HTTP session with a browser-like User-Agent. A non-browser UA (the old
# "bswan/3.2") is trivially flagged by Yahoo/Stooq throttles; reusing one keep-
# alive session across all calls also cuts connection churn.
_HTTP = requests.Session()
_HTTP.headers.update({
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "text/csv,application/json,text/html,*/*",
})

# Stooq is a free, keyless, batch-friendly quote source used as the fallback
# when yfinance (an unauthenticated Yahoo scraper) gets 429'd. Map each Yahoo
# ticker to its Stooq symbol. Futures use the continuous ".f" contracts.
STOOQ_MAP = {
    "CL=F": "cl.f",    # WTI crude, continuous
    "RB=F": "rb.f",    # RBOB gasoline
    "HO=F": "ho.f",    # heating oil / ULSD
    "BZ=F": "cb.f",    # Brent crude, continuous
    "JPY=X": "usdjpy",  # USD/JPY spot
    "SGD=X": "usdsgd",
    "HKD=X": "usdhkd",
    "MYR=X": "usdmyr",
    "QQQ": "qqq.us",
}

# ---------------------------------------------------------- holdings register
# Mirrors the §1 register + §1B tier/cluster map in the daily-briefing prompt
# (daily_briefing_prompt_v3.4.md). Kept here so the fetcher can pre-compute
# §1B weights into holdings_prices.json, freeing the briefing run from having
# to pull 31 live quotes via web search. Qty/tier/cluster are the source of
# truth Amber edits; the fetcher only ATTACHES prices (never edits the map).
# Currency is inferred from the Yahoo suffix (.SI=SGD, .T=JPY, .HK=HKD,
# .KL=MYR, else USD). SLV is a 0-share target (priced for context, 0 weight).
# `country` = primary ECONOMIC exposure, deliberately distinct from listing
# currency. US-listed ADRs/foreign ETFs (BIDU, PONY, EIDO, NTR, ...) carry
# their real country here, so the economic-geography rollup doesn't count
# them as "US" just because they trade in New York. Broad multi-country ETFs
# are "Global"; bullion is "Commodity". This is a judgment field Amber owns
# and edits, same as tier/cluster.
HOLDINGS = [
    # ticker,     qty,    tier,        cluster,           country (economic)
    ("MSFT",      140,    "Core",      "AI-complex",      "US"),
    ("BIDU",      130,    "Tactical",  "China",           "China"),
    ("GRAB",      3000,   "Starter",   "SEA",             "SEA"),
    ("PONY",      1000,   "Starter",   "China",           "China"),
    ("COUR",      177,    "Starter",   "Software",        "US"),
    ("CIA",       3000,   "Starter",   "Insurance",       "US"),
    ("ADBE",      350,    "Core",      "Software",        "US"),  # v3.6: reclassified Core (Quality-compounder override, let-run); software ADOPTER, NOT the AI-complex tail
    ("ACGL",      200,    "Tactical",  "Insurance",       "US"),
    ("OXY",       500,    "Tactical",  "WTI energy",      "US"),
    ("BAH",       1100,   "Tactical",  "Gov services",    "US"),
    ("DVN",       100,    "Tactical",  "WTI energy",      "US"),
    ("BMY",       200,    "Tactical",  "Pharma",          "US"),
    ("MRK",       -40,    "Tactical",  "Pharma",          "US"),  # NET SHORT 40 (flipped from long 80, set 2026-08-19). Buy-to-cover $135–137; cover on any rally >$137 (Amber not comfortable naked-short open-ended). Short thesis: overvalued vs old $140/$150 lines. Watch MRK ex-div (short pays the dividend).
    ("ZTS",       300,    "Tactical",  "Pharma",          "US"),  # add-on-weakness zone $60–68 (no stop); no upside line — let run (qty 100→300 set 2026-08-19)
    ("FISV",      200,    "Tactical",  "Financial",       "US"),
    ("IAUM",      150,    "Core",      "Precious metals", "Commodity"),
    ("SLV",       0,      "Starter",   "Precious metals", "Commodity"),
    ("NTR",       200,    "Tactical",  "Fertilizer/agri", "Canada"),
    ("ICLN",      450,    "Starter",   "Rates/utilities", "Global"),
    ("EIDO",      800,   "Starter",   "SEA",             "Indonesia"),
    ("KARS",      494,    "Starter",   "China",           "Global"),
    ("D05.SI",    0,    "Core",      "SG banks",        "Singapore"),
    ("U11.SI",    200,    "Core",      "SG banks",        "Singapore"),
    ("BSL.SI",    3100,   "Tactical",  "SG other",        "Singapore"),
    ("F34.SI",    2000,   "Tactical",  "Fertilizer/agri", "SEA"),  # limit-exit line: S$4.30–4.80 (updated 2026-08-05, was SGD 3.50+)
    ("U96.SI",    3400,   "Tactical",  "Rates/utilities", "Singapore"),
    ("C2PU.SI",   3800,   "Tactical",  "Rates/utilities", "Singapore"),
    ("HMN.SI",    11800,   "Tactical",  "Rates/utilities", "Singapore"),
    ("8664.KL",   89000,  "Exit",      "MY other",        "Malaysia"),
    ("7203.T",    800,    "Core",      "Japan",           "Japan"),
    ("8001.T",    300,    "Tactical",  "Japan",           "Japan"),
    ("2026.HK",   2100,   "Starter",   "China",           "China"),
    ("9961.HK",   950,    "Tactical",  "China",           "China"),
    ("TME",       3000,    "Tactical",  "China",           "China"),
]

# Watchlist: priced for monitoring only. NOT held, NOT part of the 31-name
# register, and excluded from portfolio value, §1B weights, and all cap math.
# ticker,     country (economic)
WATCHLIST = [
    ("Z74.SI",    "Singapore"),  # Singtel (SGX)
]

# §1B cluster caps (% of portfolio). PONY+2026.HK aggregate as one issuer
# inside the China cluster before any cap math (issuer rule). v3.6: the retired
# "AI mega-cap" cluster is SPLIT — the AI-complex tail (MSFT + PONY/2026.HK) is
# uncapped while preservation >=30% (a cross-cluster readout the briefing
# computes; not a flat cap here), and "Software" (ADBE, COUR) is monitoring-only.
# Neither carries a hard cluster cap, so both are omitted below (=> "no cap").
CLUSTER_CAPS = {
    "China": 15.0, "WTI energy": 12.0,
    "Rates/utilities": 20.0, "SG banks": 18.0, "Fertilizer/agri": 10.0,
    "Japan": 15.0, "Precious metals": 15.0, "Pharma": 10.0,
}
# v3.6 two-tier conviction system. Soft = monitoring line; hard = never-override
# ceiling (the 25% "Apple ceiling" for Core). Size alone is not a sell signal
# for a Core name below its hard ceiling.
TIER_SOFT_CAP = {"Core": 20.0, "Tactical": 8.0, "Starter": 4.0, "Exit": 0.0}
TIER_HARD_CEILING = {"Core": 25.0, "Tactical": 10.0, "Starter": 5.0, "Exit": 0.0}
US_GEO_CAP = 40.0

# Preservation sleeve — cash + T-bills. NOT exchange-priced: these are Amber's
# actual USD balances, entered and edited by hand here. They ARE part of the
# total portfolio — every tier/cluster cap and the AI-complex uncap gate is
# measured as % of TOTAL (equities + preservation). The % drifts naturally as
# equity marks move, which is correct: balances are fixed dollars, not fixed %.
# Confirmed 2026-08-11 (Amber): cash ~10%, T-bills ~25% of total (~35% sleeve).
# Back-computed from the 2026-08-11 equity mark ($600,226 = 65% of total).
# Edit these dollar figures whenever balances change.
PRESERVATION = {
    "cash_usd":  92342.49,   # ~10% of total at 2026-08-11 equity mark
    "tbill_usd": 230856.23,  # ~25% of total at 2026-08-11 equity mark
}


def _ccy_of(ticker):
    if ticker.endswith(".SI"):
        return "SGD"
    if ticker.endswith(".T"):
        return "JPY"
    if ticker.endswith(".HK"):
        return "HKD"
    if ticker.endswith(".KL"):
        return "MYR"
    return "USD"

# ---------------------------------------------------------------- paths / env
SCRIPT_DIR = Path(__file__).resolve().parent
OUT_PATH = SCRIPT_DIR / "daily_readings.json"
HOLDINGS_PATH = SCRIPT_DIR / "holdings_prices.json"
SGT = timezone(timedelta(hours=8))

# load .env if present
env_file = SCRIPT_DIR / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

FRED_KEY = os.environ.get("FRED_API_KEY", "")

FRED_SERIES = {
    "ust10": "DGS10",
    "ust30": "DGS30",
    "breakeven10": "T10YIE",
    "hy_oas": "BAMLH0A0HYM2",
    "ig_oas": "BAMLC0A0CM",
    # FERTILIZER NOTE: PFOODINDEXM = IMF global food price index (monthly).
    # PCU325311325311 = US PPI, nitrogenous fertilizer mfg (monthly), a robust
    # proxy for urea/ammonia. For World Bank Pink Sheet urea/DAP levels,
    # replace fetch_fred_yoy with a Pink Sheet xlsx parser (URL changes each
    # monthly release, hence not automated here).
    "food_index": "PFOODINDEXM",
    "fertilizer_ppi": "PCU325311325311",
    # v3.2 addition: Fed Z.1 broker/dealer margin credit extended to customers,
    # quarterly $millions. Broader than pure FINRA retail margin debt (covers
    # institutional too) but tracks the same cycle. Quarterly ~2mo lag; fine
    # for a slow-moving amplifier signal.
    "margin_debt": "BOGZ1FL663067003Q",
}

# v3.2 additions — non-FRED sources for the us_equity_excess card and
# the private-credit automation.
MULTPL_CAPE_URL = "https://www.multpl.com/shiller-pe"
FITCH_LSTA_URL = "https://www.lsta.org/content/fitch-ratings-commentary-page/"


MOF_JGB_CSV = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv"
TD_AUCTION_API = "https://www.treasurydirect.gov/TA_WS/securities/auctioned"
WHO_DON_RSS = "https://www.who.int/rss-feeds/news-english.xml"

WEAK_AUCTION_B2C = 2.20  # 30y bid-to-cover below this = weak auction

status = {}


def log(msg):
    print(f"[{datetime.now(SGT):%Y-%m-%d %H:%M:%S}] {msg}")


# ================================================================ fetch layer
def fetch_fred_latest(series_id):
    r = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={
            "series_id": series_id,
            "api_key": FRED_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 15,
        },
        timeout=60,
    )
    r.raise_for_status()
    for obs in r.json().get("observations", []):
        if obs["value"] not in (".", ""):
            return float(obs["value"]), obs["date"]
    return None, None


def fetch_fred_yoy(series_id):
    """Latest value + year-over-year % change for monthly series."""
    r = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={
            "series_id": series_id,
            "api_key": FRED_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 15,
        },
        timeout=60,
    )
    r.raise_for_status()
    obs = [o for o in r.json().get("observations", []) if o["value"] not in (".", "")]
    if not obs:
        return None, None, None
    latest_val, latest_date = float(obs[0]["value"]), obs[0]["date"]
    target = (datetime.fromisoformat(latest_date) - timedelta(days=365)).date()
    r2 = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={
            "series_id": series_id,
            "api_key": FRED_KEY,
            "file_type": "json",
            "observation_start": str(target - timedelta(days=45)),
            "observation_end": str(target + timedelta(days=45)),
        },
        timeout=60,
    )
    r2.raise_for_status()
    prior = [o for o in r2.json().get("observations", []) if o["value"] not in (".", "")]
    yoy = None
    if prior:
        base = float(prior[-1]["value"])
        if base:
            yoy = round((latest_val / base - 1) * 100, 1)
    return latest_val, yoy, latest_date


def _is_rate_limit(err):
    m = str(err).lower()
    return "too many" in m or "429" in m or "rate limit" in m or "rate-limit" in m


def fetch_yf_batch(tickers, period="10d", retries=4):
    """Batched last-close pull for many tickers in ONE yfinance download call.

    Replaces the old per-ticker yf.Ticker().history() loop, which fired one
    HTTP request per symbol in a burst — the pattern Yahoo throttles. Retries
    on 429 with exponential backoff + jitter. Returns {ticker: last_close};
    silently omits any symbol that didn't come back.
    """
    if not HAVE_YF or not tickers:
        return {}
    last_err = None
    for attempt in range(retries):
        try:
            data = yf.download(tickers, period=period, interval="1d",
                               group_by="ticker", threads=False,
                               progress=False, auto_adjust=False)
            out = {}
            for t in tickers:
                try:
                    ser = data["Close"] if len(tickers) == 1 else data[t]["Close"]
                    ser = ser.dropna()
                    if len(ser):
                        out[t] = float(ser.iloc[-1])
                except Exception:
                    pass
            if out:
                return out
            # empty frame usually means a soft throttle — back off and retry
            last_err = RuntimeError("empty frame (possible soft rate-limit)")
        except Exception as e:
            last_err = e
        if attempt < retries - 1:
            time.sleep((2 ** attempt) + random.uniform(0, 1.5))
    if last_err:
        raise last_err
    return {}


def fetch_stooq_last(ticker):
    """Keyless single-quote fallback from Stooq. Returns float or None."""
    sym = STOOQ_MAP.get(ticker)
    if not sym:
        return None
    try:
        r = _HTTP.get("https://stooq.com/q/l/",
                      params={"s": sym, "f": "sd2t2ohlcv", "h": "", "e": "csv"},
                      timeout=20)
        r.raise_for_status()
        lines = r.text.strip().splitlines()
        if len(lines) < 2:
            return None
        row = dict(zip(lines[0].split(","), lines[1].split(",")))
        close = row.get("Close")
        if close in (None, "", "N/D"):
            return None
        return float(close)
    except Exception:
        return None


def fetch_market_prices(tickers):
    """Batched yfinance first, Stooq fallback for whatever's missing.

    Returns (prices_dict, yf_error_or_None, list_of_tickers_filled_by_stooq).
    Never raises — a total yfinance failure just means everything is sourced
    from Stooq (or held-last if both miss).
    """
    prices, yf_err = {}, None
    try:
        prices = fetch_yf_batch(tickers)
    except Exception as e:
        yf_err = e
    stooq_used = []
    for t in tickers:
        if t not in prices:
            v = fetch_stooq_last(t)
            if v is not None:
                prices[t] = v
                stooq_used.append(t)
    return prices, yf_err, stooq_used


def fetch_crack_spread(prices):
    """3-2-1 crack: (2*RBOB + 1*HO)*42 - 3*WTI, per 3 bbl -> per bbl."""
    wti, rb, ho = prices.get("CL=F"), prices.get("RB=F"), prices.get("HO=F")
    if None in (wti, rb, ho):
        return None, wti
    crack = ((2 * rb * 42) + (ho * 42) - (3 * wti)) / 3
    return round(crack, 2), wti


def fetch_qqq_drawdown():
    """QQQ drawdown-from-1y-peak, %. yfinance (with backoff) then Stooq daily CSV."""
    if HAVE_YF:
        for attempt in range(4):
            try:
                hist = yf.download("QQQ", period="1y", interval="1d",
                                   progress=False, threads=False, auto_adjust=False)
                close = hist["Close"].dropna().squeeze()
                if len(close):
                    return round((float(close.iloc[-1]) / float(close.max()) - 1) * 100, 1)
                raise RuntimeError("empty frame")
            except Exception as e:
                if attempt < 3 and _is_rate_limit(e) or attempt < 3:
                    time.sleep((2 ** attempt) + random.uniform(0, 1.5))
                    continue
                break
    # Stooq daily-history fallback
    try:
        r = _HTTP.get("https://stooq.com/q/d/l/", params={"s": "qqq.us", "i": "d"}, timeout=25)
        r.raise_for_status()
        rows = list(csv.reader(io.StringIO(r.text)))
        if len(rows) < 2 or "Close" not in rows[0]:
            return None
        ci = rows[0].index("Close")
        closes = [float(x[ci]) for x in rows[1:]
                  if len(x) > ci and x[ci] not in ("", "N/D")]
        closes = closes[-260:]  # ~1y of trading days
        if closes:
            return round((closes[-1] / max(closes) - 1) * 100, 1)
    except Exception:
        return None
    return None


def fetch_holdings_prices():
    """Price all §1 holdings, convert to USD, compute §1B weights + caps.

    Writes nothing itself — returns the dict main() serializes to
    holdings_prices.json. Uses the same batched-yfinance + Stooq fallback as
    the market feed, so the 31-name pull is ONE download, not 31 requests.

    FX convention: Yahoo "SGD=X" etc. quote LOCAL units per 1 USD, so
    price_usd = local_price / fx_units_per_usd. USD names use rate 1.0.
    """
    now = datetime.now(SGT)
    tickers = [h[0] for h in HOLDINGS]
    watch_tickers = [w[0] for w in WATCHLIST]

    # --- prices (one batched call + Stooq fill) ---
    # Include watchlist in the same batch so it's one download; watchlist is
    # priced for monitoring only and never enters weight/cap math below.
    prices, yf_err, stooq_used = fetch_market_prices(tickers + watch_tickers)

    # --- FX rates (units of local per 1 USD) ---
    need_ccy = {_ccy_of(t) for t in tickers + watch_tickers} - {"USD"}
    fx_tickers = [f"{c}=X" for c in need_ccy]
    fx_raw, _, fx_stooq = fetch_market_prices(fx_tickers) if fx_tickers else ({}, None, [])
    fx = {"USD": 1.0}
    for c in need_ccy:
        v = fx_raw.get(f"{c}=X")
        if v:
            fx[c] = v

    # --- per-position valuation ---
    positions, unpriced = [], []
    equity_total_usd = 0.0
    for ticker, qty, tier, cluster, country in HOLDINGS:
        ccy = _ccy_of(ticker)
        px = prices.get(ticker)
        rate = fx.get(ccy)
        if px is None or rate is None:
            unpriced.append(ticker)
            positions.append({"ticker": ticker, "qty": qty, "ccy": ccy,
                              "tier": tier, "cluster": cluster, "country": country,
                              "price": None, "value_usd": None,
                              "weight_pct": None, "source": "unpriced"})
            continue
        value_usd = qty * px / rate
        equity_total_usd += value_usd
        positions.append({"ticker": ticker, "qty": qty, "ccy": ccy,
                          "tier": tier, "cluster": cluster, "country": country,
                          "price": round(px, 4), "value_usd": round(value_usd, 2),
                          "weight_pct": None,  # filled after total is known
                          "source": "stooq" if ticker in stooq_used else "yfinance"})

    # --- preservation sleeve (cash + T-bills) ---
    # Manual USD balances, added as pseudo-positions so §1B weights reconcile to
    # 100% and the denominator is the TRUE total (equities + preservation). They
    # carry a "Preservation" tier/cluster/country so they never distort the
    # equity concentration readouts (US-equity geo, AI-complex tail, etc.).
    cash_usd = float(PRESERVATION.get("cash_usd", 0.0))
    tbill_usd = float(PRESERVATION.get("tbill_usd", 0.0))
    preservation_usd = cash_usd + tbill_usd
    if cash_usd > 0:
        positions.append({"ticker": "CASH", "qty": None, "ccy": "USD",
                          "tier": "Preservation", "cluster": "Preservation",
                          "country": "Preservation", "price": None,
                          "value_usd": round(cash_usd, 2), "weight_pct": None,
                          "source": "manual"})
    if tbill_usd > 0:
        positions.append({"ticker": "TBILL", "qty": None, "ccy": "USD",
                          "tier": "Preservation", "cluster": "Preservation",
                          "country": "Preservation", "price": None,
                          "value_usd": round(tbill_usd, 2), "weight_pct": None,
                          "source": "manual"})
    total_usd = equity_total_usd + preservation_usd

    # --- weights + rollups (issuer rule PONY+2026.HK already in China cluster) ---
    # Weights are % of TOTAL (equities + preservation). Two geography views:
    #   geo_listing  = by listing currency (USD == "US"); cheap proxy, overstates
    #                  US by counting ADRs / foreign ETFs that trade in New York.
    #   geo_economic = by the `country` field = real country of business.
    #   Preservation rows are excluded from the US-equity geo views (they are
    #   sovereign cash, not equity country risk).
    clusters, econ_geo, geo_us_listing = {}, {}, 0.0
    for p in positions:
        if p["value_usd"] is None or total_usd <= 0:
            continue
        w = round(p["value_usd"] / total_usd * 100, 2)
        p["weight_pct"] = w
        clusters[p["cluster"]] = round(clusters.get(p["cluster"], 0.0) + w, 2)
        econ_geo[p["country"]] = round(econ_geo.get(p["country"], 0.0) + w, 2)
        if p["ccy"] == "USD" and p["tier"] != "Preservation":
            geo_us_listing = round(geo_us_listing + w, 2)

    cluster_rows = {}
    for name, w in sorted(clusters.items(), key=lambda kv: -kv[1]):
        cap = CLUSTER_CAPS.get(name)
        cluster_rows[name] = {
            "weight_pct": w, "cap_pct": cap,
            "state": ("OVER CAP" if cap and w > cap else "CLEAR" if cap else "no cap"),
            "headroom_pct": (round(cap - w, 2) if cap else None),
        }

    priced_n = len(tickers) - len(unpriced)
    # v3.5: hold-last guard. On a networkless / soft-rate-limited run the batch
    # returns an empty frame -> every name unpriced and total_usd == 0. Writing
    # that would zero holdings_prices.json (coverage 0/32, pv $0). Raise instead
    # so main()'s except retains the prior good file and flags it held-last.
    if priced_n == 0 or equity_total_usd <= 0:
        raise RuntimeError(
            f"holdings price batch empty ({len(unpriced)}/{len(tickers)} unpriced, "
            f"equity_total=${equity_total_usd:.2f}) — retaining prior holdings_prices.json"
            + (f"; yf: {str(yf_err).split(chr(10))[0][:60]}" if yf_err else ""))

    # --- watchlist (monitoring only; no weight, no cap, not in portfolio value) ---
    watchlist_rows = []
    for ticker, country in WATCHLIST:
        ccy = _ccy_of(ticker)
        px = prices.get(ticker)
        rate = fx.get(ccy)
        if px is None or rate is None:
            watchlist_rows.append({"ticker": ticker, "ccy": ccy, "country": country,
                                   "price": None, "price_usd": None, "source": "unpriced"})
            continue
        watchlist_rows.append({
            "ticker": ticker, "ccy": ccy, "country": country,
            "price": round(px, 4), "price_usd": round(px / rate, 4),
            "source": "stooq" if ticker in stooq_used else "yfinance"})

    return {
        "schema": "bswan-holdings-v1",
        "as_of": now.isoformat(timespec="seconds"),
        "base_ccy": "USD",
        "coverage": f"{priced_n}/{len(tickers)} priced",
        "portfolio_value_usd": round(total_usd, 2),   # equities + preservation
        "equity_value_usd": round(equity_total_usd, 2),
        "preservation": {
            "cash_usd": round(cash_usd, 2),
            "tbill_usd": round(tbill_usd, 2),
            "preservation_usd": round(preservation_usd, 2),
            "preservation_pct": (round(preservation_usd / total_usd * 100, 2)
                                 if total_usd > 0 else None),
            "ai_complex_gate": (
                "OK (>=30%)" if total_usd > 0 and preservation_usd / total_usd * 100 >= 30
                else "BREACH (<30%)" if total_usd > 0 else "unknown"),
            "note": ("manual cash+T-bill balances; weights are % of TOTAL "
                     "(equities+preservation); sleeve >=30% keeps the "
                     "AI-complex tail uncapped"),
        },
        "fx_units_per_usd": {k: round(v, 4) for k, v in fx.items() if k != "USD"},
        "fx_note": "local units per 1 USD; price_usd = price / rate",
        "tier_soft_caps_pct": TIER_SOFT_CAP,
        "tier_hard_ceilings_pct": TIER_HARD_CEILING,
        "positions": positions,
        "watchlist": watchlist_rows,
        "clusters": cluster_rows,
        "geography_listing": {  # by listing currency — overstates US (ADRs/ETFs)
            "US": {"weight_pct": geo_us_listing, "cap_pct": US_GEO_CAP,
                   "state": "OVER CAP" if geo_us_listing > US_GEO_CAP else "CLEAR",
                   "headroom_pct": round(US_GEO_CAP - geo_us_listing, 2)},
        },
        "geography_economic": {  # by country of business — the real exposure
            name: {"weight_pct": w,
                   "cap_pct": (US_GEO_CAP if name == "US" else None),
                   "state": ("OVER CAP" if name == "US" and w > US_GEO_CAP
                             else "CLEAR" if name == "US" else "no cap"),
                   "headroom_pct": (round(US_GEO_CAP - w, 2) if name == "US" else None)}
            for name, w in sorted(econ_geo.items(), key=lambda kv: -kv[1])
        },
        "unpriced": unpriced,
        "source_note": (f"yfinance batched; stooq fallback: "
                        f"{','.join(stooq_used + fx_stooq) or 'none'}"
                        + (f"; yf soft-fail: {str(yf_err).split(chr(10))[0][:40]}"
                           if yf_err else "")),
    }


def fetch_jgb():
    """Parse Japan MoF daily yield curve CSV. Returns dict of tenor -> yield."""
    r = requests.get(MOF_JGB_CSV, timeout=30)
    r.raise_for_status()
    text = r.content.decode("shift_jis", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    # locate header row containing tenor labels like 1Y ... 40Y
    header_i = next(
        (i for i, row in enumerate(rows) if any("10" in c and "Y" in c.upper() for c in row)),
        None,
    )
    if header_i is None:
        return {}
    header = [c.strip().upper().replace("YEAR", "Y") for c in rows[header_i]]
    # last non-empty data row whose first column is a date (YYYY/MM/DD or YYYY/M/D)
    # Rows that fail this check are footer notes like "※If you cannot download..."
    _date_re = re.compile(r'^\d{4}/\d{1,2}/\d{1,2}$')
    data = next(
        (row for row in reversed(rows)
         if len(row) == len(header) and _date_re.match(row[0].strip())),
        None,
    )
    if not data:
        return {}
    out = {}
    for tenor, key in (("10Y", "jgb10"), ("30Y", "jgb30"), ("40Y", "jgb40")):
        if tenor in header:
            try:
                out[key] = float(data[header.index(tenor)])
            except (ValueError, IndexError):
                pass
    out["jgb_date"] = data[0].strip()
    return out


def fetch_treasury_b2c():
    """Latest 10y note & 30y bond bid-to-cover from TreasuryDirect."""
    out = {}
    for sec_type, term_frag, key in (("Note", "10-", "bid_to_cover_10y"),
                                     ("Bond", "30-", "bid_to_cover_30y")):
        r = requests.get(
            TD_AUCTION_API,
            params={"format": "json", "type": sec_type, "days": 120},
            timeout=30,
        )
        r.raise_for_status()
        for a in r.json():
            if term_frag in (a.get("securityTerm") or "") or \
               term_frag in (a.get("originalSecurityTerm") or ""):
                b2c = a.get("bidToCoverRatio")
                if b2c not in (None, "", "null"):
                    out[key] = round(float(b2c), 2)
                    out[key + "_date"] = (a.get("auctionDate") or "")[:10]
                    break
    return out


def fetch_pandemic_tier():
    """Manual monthly signal — see manual.pandemic_tier_manual in JSON."""
    return None


# ================================================================ v3.2 fetchers
# Three new data pulls to power the us_equity_excess card + private-credit
# automation. Each is defensive: returns None on failure, never raises.

def fetch_margin_debt_yoy():
    """FINRA monthly margin debt YoY growth, with FRED quarterly fallback.

    FINRA publishes debit balances in customer margin accounts monthly
    (~2-month lag), substantially fresher than the Fed Z.1 quarterly series
    (~5-month lag). We parse the FINRA margin-statistics page HTML table,
    match the latest month to the same month a year prior, and compute YoY.

    Falls back to FRED `BOGZ1FL663067003Q` (quarterly) when FINRA fails.

    Returns (level_bn, yoy_pct, asof_date) or (None, None, None).
    """
    # --- FINRA monthly (primary) ---
    try:
        r = requests.get(
            "https://www.finra.org/investors/learn-to-invest/advanced-investing/margin-statistics",
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()
        # Parse table rows: Mon-YY, Debit $M, ...
        _months = "January February March April May June July August September October November December".split()
        _abbr = {m[:3]: m for m in _months}
        rows_raw = re.findall(r'<tr[^>]*>(.*?)</tr>', r.text, re.DOTALL | re.IGNORECASE)
        parsed = []
        for row in rows_raw:
            cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.DOTALL | re.IGNORECASE)
            cleaned = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            m2 = re.match(r'^([A-Z][a-z]{2})-(\d{2})$', cleaned[0]) if cleaned else None
            if m2 and len(cleaned) >= 2:
                month_abbr, yr2 = m2.group(1), int(m2.group(2))
                full_month = _abbr.get(month_abbr)
                if not full_month:
                    continue
                year = 2000 + yr2
                debit_m = float(cleaned[1].replace(",", ""))
                parsed.append((year, _months.index(full_month) + 1, debit_m))
        if len(parsed) >= 13:
            latest = parsed[0]
            # find same month prior year
            prior = next((p for p in parsed if p[0] == latest[0] - 1 and p[1] == latest[1]), None)
            if prior:
                level_bn = round(latest[2] / 1000, 1)
                yoy = round((latest[2] / prior[2] - 1) * 100, 1)
                last_day = calendar.monthrange(latest[0], latest[1])[1]
                asof = f"{latest[0]}-{latest[1]:02d}-{last_day:02d}"
                return level_bn, yoy, asof
    except Exception:
        pass

    # --- FRED quarterly fallback ---
    if not FRED_KEY:
        return None, None, None
    try:
        r = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={"series_id": FRED_SERIES["margin_debt"],
                    "api_key": FRED_KEY, "file_type": "json",
                    "sort_order": "desc", "limit": 8},
            timeout=60)
        r.raise_for_status()
        obs = [o for o in r.json().get("observations", [])
               if o["value"] not in (".", "")]
        if len(obs) < 5:
            return None, None, None
        latest_v = float(obs[0]["value"]) / 1000
        prior_v = float(obs[4]["value"]) / 1000
        yoy = round((latest_v / prior_v - 1) * 100, 1) if prior_v else None
        return round(latest_v, 1), yoy, obs[0]["date"]
    except Exception:
        return None, None, None


def fetch_shiller_cape():
    """Scrape current Shiller CAPE (P/E10) from multpl.com.

    Multiple regex patterns tried in order of reliability:
      1. meta-description tag: 'Current Shiller PE Ratio is 41.85' (most stable)
      2. body text: '**Current Shiller PE Ratio:** ... 41.85' with tags between
      3. plain 'Current Shiller PE Ratio: 41.85' fallback
    Returns (cape_value, asof_string) or (None, None).
    """
    try:
        r = _HTTP.get(MULTPL_CAPE_URL, timeout=20)
        r.raise_for_status()
        html = r.text
        cape = None
        # Pattern 1: meta description — most reliable
        m = re.search(r'Current\s+Shiller\s+PE\s+Ratio\s+is\s+([0-9]+\.[0-9]+)',
                      html, re.IGNORECASE)
        # Pattern 2: displayed text with tags between label and value
        if not m:
            m = re.search(
                r'Current\s+Shiller\s+PE\s+Ratio[^0-9]{0,200}?([0-9]{1,3}\.[0-9]{2})',
                html, re.IGNORECASE | re.DOTALL)
        # Pattern 3: original tight pattern (in case multpl restructures back)
        if not m:
            m = re.search(r'Current\s+Shiller\s+PE\s+Ratio:\s*([0-9]+\.[0-9]+)',
                          html, re.IGNORECASE)
        if not m:
            return None, None
        cape = float(m.group(1))
        # Sanity: CAPE has never been below 4 or above 50 in recorded history
        if not (4 <= cape <= 55):
            return None, None
        # Timestamp: multpl.com prints "4:00 PM EDT, Mon Jul 13" near the number
        d = re.search(r'\d+:\d+\s+[AP]M\s+[A-Z]{2,4},?\s+([A-Z][a-z]+\s+[A-Z][a-z]+\s+\d+)',
                      html)
        asof = d.group(1) if d else datetime.now(SGT).strftime("%Y-%m-%d")
        return round(cape, 2), asof
    except Exception:
        return None, None


_FITCH_MONTHS = ("January February March April May June July August "
                 "September October November December").split()


def _fitch_parse(html, today=None):
    """Pure parser (unit-testable). Returns (rate|None, 'Month YYYY'|None, post_date).

    v3.2b (2026-10-05): the old regexes required the literal phrase
    "Private Credit Default Rate" inside a single tag-free run, and a
    year after the month. LSTA/Fitch headlines now vary ("U.S. Private
    Credit Defaults Climb to 6.3% in August", "...Hits Record 6.3%..."),
    and titles are often split by inline tags — both gave parse-empty.
    Now: strip tags, find every sentence-sized window mentioning private
    credit + default, pull %, month and (optional) year, return the newest.
    """
    today = today or datetime.now().date()
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"\s+", " ", text)
    mon = "|".join(_FITCH_MONTHS)
    best = None  # (key, rate, month_year, post)
    for m in re.finditer(r"private\s+credit\s+default", text, re.I):
        win = text[m.start():m.start() + 220]
        mm = re.search(rf"\b({mon})\b(?:\s+(\d{{4}}))?", win)
        if not mm:
            continue
        month = mm.group(1)
        year = int(mm.group(2)) if mm.group(2) else None
        post_m = re.search(rf"\b((?:{mon})\s+\d{{1,2}},\s+\d{{4}})",
                           text[max(0, m.start() - 250):m.start() + 450])
        post = post_m.group(1) if post_m else None
        if year is None:
            # Infer: data month is never after the post/today date.
            ref = datetime.strptime(post, "%B %d, %Y").date() if post else today
            mi = _FITCH_MONTHS.index(month) + 1
            year = ref.year if mi <= ref.month else ref.year - 1
        rate_m = re.search(r"(\d{1,2}(?:\.\d)?)\s*%", win[:mm.start() + 40])
        rate = float(rate_m.group(1)) if rate_m else None
        if rate is not None and not (0.5 <= rate <= 25):
            rate = None
        key = (year, _FITCH_MONTHS.index(month) + 1, rate is not None)
        month_year = f"{month} {year}"
        if best is None or key > best[0]:
            best = (key, rate, month_year, post or month_year)
    if best is None:
        return None, None, None
    return best[1], best[2], best[3]


def fetch_fitch_private_credit_rate():
    """Scrape Fitch's latest US private credit default rate from LSTA.

    Returns (rate_pct, month_year_str, post_date_str) or (None, None, None).
    rate_pct is None when only the period could be parsed — caller then
    refreshes asof only. Network/HTTP errors now RAISE (caller reports
    'fail: ...') instead of masquerading as parse-empty. On parse-empty
    the raw page is saved to fitch_debug.html for diagnosis.
    """
    r = _HTTP.get(FITCH_LSTA_URL, timeout=20)
    r.raise_for_status()
    result = _fitch_parse(r.text)
    if result[1] is None:
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "fitch_debug.html"), "w") as f:
                f.write(r.text)
        except OSError:
            pass
    return result


def tier_us_equity_excess(a, m):
    """Combined margin debt YoY + Shiller CAPE.

    Both inputs measure the same underlying condition — how stretched
    US equity valuations and leverage are versus history — but from
    different angles (retail borrowing behavior vs cyclically-adjusted
    earnings). Card fires on WHICHEVER is more elevated.

    Thresholds calibrated against 2000, 2007, 2021 peaks:
      margin_debt_yoy: <10 calm, 10-25 watch, 25-40 elevated, >40 extreme
      cape:            <25 calm, 25-30 watch, 30-38 elevated, >38 extreme
                       (dot-com peak was 44.2)
    Card tier = max(leverage_tier, valuation_tier).
    """
    yoy = a.get("margin_debt_yoy")
    cape = m.get("cape_manual")
    if a.get("cape_auto") is not None:
        cape = a.get("cape_auto")  # auto scrape wins when present
    if yoy is None and cape is None:
        return None
    lev_t = None
    if yoy is not None:
        lev_t = 0 if yoy < 10 else 1 if yoy < 25 else 2 if yoy <= 40 else 3
    val_t = None
    if cape is not None:
        val_t = 0 if cape < 25 else 1 if cape < 30 else 2 if cape <= 38 else 3
    return max(t for t in (lev_t, val_t) if t is not None)


# ============================================================ hazard model v3
# Mirrored in black_swan_dashboard_v3.html (function computeModel).
# Change thresholds in BOTH files.

def tier_energy(a):
    wti = a.get("wti")
    if wti is None:
        return None
    t = 0 if wti < 85 else 1 if wti < 95 else 2 if wti <= 110 else 3
    if (a.get("crack_spread_321") or 0) > 45 and t < 3:
        t += 1
    return t


def tier_ust(a):
    b2c, y30 = a.get("bid_to_cover_30y"), a.get("ust30")
    if b2c is None and y30 is None:
        return None
    t = 0
    if b2c is not None:
        t = 0 if b2c > 2.4 else 1 if b2c > 2.2 else 2 if b2c > 2.0 else 3
    if y30 is not None:
        if y30 > 5.25:
            t = 3
        elif y30 > 5.0:
            t = max(t, 2)
    return t


def tier_jgb(a):
    j10 = a.get("jgb10")
    if j10 is None:
        return None
    t = 0 if j10 < 2.0 else 1 if j10 < 2.5 else 2 if j10 <= 3.0 else 3
    if (a.get("jgb30") or 0) > 4.2:
        t = 3
    if (a.get("usdjpy") or 0) > 162 and t < 3:
        t += 1
    return t


def tier_private_credit(m):
    d = m.get("true_default_rate_pct")
    if d is None:
        return None
    t = 0 if d < 4 else 1 if d < 5 else 2 if d <= 8 else 3
    if (m.get("redemption_gates_count") or 0) >= 2:
        t = 3
    return t


def tier_ai_nexus(a, m):
    cuts = m.get("hyperscaler_guidance_cuts") or 0
    dd = a.get("qqq_drawdown_pct")
    ig = a.get("ig_oas")
    t = 1  # panel baseline: late-cycle watch
    if cuts >= 2 or (dd is not None and dd < -25):
        t = 3
    elif cuts >= 1 or (dd is not None and dd < -15) or (ig is not None and ig > 1.6):
        t = 2
    elif dd is not None and dd > -3 and (ig is not None and ig < 1.0) and cuts == 0:
        t = 0
    return t


def tier_fertilizer(a):
    f = a.get("fertilizer_ppi_yoy")
    if f is None:
        return None
    t = 0 if f < 15 else 1 if f < 30 else 2 if f <= 60 else 3
    if (a.get("food_index_yoy") or 0) > 20 and t < 3:
        t += 1
    return t


def compute_model(auto, manual, falsifiers):
    tiers = {
        "energy": tier_energy(auto),
        "ust_rollover": tier_ust(auto),
        "jgb_snapback": tier_jgb(auto),
        "private_credit": tier_private_credit(manual),
        "ai_nexus": tier_ai_nexus(auto, manual),
        # v3.2: broader retail leverage + market-wide valuation stretch.
        # Sits OUTSIDE the AI-credit cluster because it captures whole-
        # market conditions (all US equities, not just AI complex).
        "us_equity_excess": tier_us_equity_excess(auto, manual),
        "taiwan": manual.get("taiwan_tier_manual"),
        "sea_policy": manual.get("sea_policy_tier_manual"),
        "pandemic": manual.get("pandemic_tier_manual"),
        "fertilizer": tier_fertilizer(auto)
    }

    # --- correlation-weighted effective count (elevated = tier >= 2) ---
    # Clusters codify signals that load on one underlying factor:
    #   Hormuz factor    = energy + fertilizer (physical supply chain)
    #   AI-credit factor = private_credit + ai_nexus
    # Two cards firing inside a cluster contribute 1.5, not 2.0 — one story
    # counted honestly.
    elevated = {k for k, v in tiers.items() if v is not None and v >= 2}
    clusters = [{"energy", "fertilizer"}, {"private_credit", "ai_nexus"}]
    eff = 0.0
    clustered = set()
    for cl in clusters:
        hit = cl & elevated
        clustered |= cl
        eff += 1.5 if len(hit) == 2 else float(len(hit))
    eff += len(elevated - clustered)

    # --- Market Convergence hazard: base map, linear between anchors ---
    # v3.2: extended to 8 (was 6) — new us_equity_excess card can add up
    # to 1 effective signal (it's outside all clusters). Anchor 7-8 use
    # a shallower slope reflecting that at very high effective counts,
    # additional signals are redundant.
    anchors = {0: 8, 1: 16, 2: 26, 3: 36, 4: 46, 5: 54, 6: 62, 7: 68, 8: 72}
    e = min(eff, 8)
    lo = int(e)
    base = anchors[lo] + (anchors[min(lo + 1, 7)] - anchors[lo]) * (e - lo)

    # --- escalators (monotone ratchets, capped +12) ---
    esc = 0.0
    since = manual.get("hormuz_closed_since")
    hormuz_months = 0.0
    if since:
        hormuz_months = (datetime.now(SGT).date() - datetime.fromisoformat(since).date()).days / 30.44
        esc += min(max(hormuz_months - 3, 0) * 2, 6)  # +2/mo beyond month 3, cap 6
    esc += min((manual.get("weak_auction_count") or 0) * 2, 4)
    if (manual.get("pik_rising_quarters") or 0) >= 4:
        esc += 2
    esc = min(esc, 12)

    # --- falsifier credits (pre-registered, mechanical) ---
    cred = 0
    if falsifiers.get("ceasefire_and_reopening"):
        cred += 15
    if falsifiers.get("hyperscaler_two_quarters_held"):
        cred += 8
    if falsifiers.get("true_defaults_rolling_over"):
        cred += 8
    if falsifiers.get("jgb_auctions_normalized"):
        cred += 5

    mc = max(round(base + esc - cred), 5)

    # --- Systemic Crisis = MC x containment-failure (policy space) ---
    cuts = manual.get("fed_cuts_priced_2026")
    factor = 0.45 if (cuts is None or cuts <= 1) else 0.38 if cuts <= 3 else 0.28
    sc = round(mc * factor)

    # --- regime ---
    # v3.2: threshold bumped from 5 -> 5.5 when us_equity_excess added a 10th
    # signal. The panel calibrated "5 elevated of 9 = >55%" as the Systemic
    # trigger; preserving that ratio at 10 signals means the threshold shifts
    # to 5.5 (equivalent to "55% of framework firing"). This is a mechanical
    # recalibration, not a discretionary softening.
    if eff >= 5.5 and factor >= 0.45 or sc >= 30:
        regime = "SYSTEMIC CRISIS"
    elif eff >= 3 or mc >= 40:
        regime = "MARKET CONVERGENCE"
    elif eff > 1:
        regime = "COUPLING"
    else:
        regime = "CONTAINED"

    return {
        "tiers": tiers,
        "effective_count": round(eff, 2),
        "hormuz_months": round(hormuz_months, 1),
        "escalator_pts": round(esc, 1),
        "falsifier_credit": cred,
        "mc_hazard": mc,
        "sc_hazard": sc,
        "containment_factor": factor,
        "regime": regime,
    }


# ==================================================================== main
def main():
    log("Black Swan fetcher v3 starting")

    # ---- load prior file: preserve manual + falsifiers + history ----
    prior = {}
    if OUT_PATH.exists():
        try:
            prior = json.loads(OUT_PATH.read_text())
        except Exception:
            log("WARN: could not parse existing daily_readings.json; starting fresh")

    auto = dict(prior.get("auto", {}))

    # Merge defaults with prior — prior wins on overlap, defaults fill any gaps.
    # (Fixes v2 migration bug: previously, a non-empty v2 manual block short-
    # circuited the defaults, leaving new v3 fields as None and zeroing tiers.)
    manual_defaults = {
        "true_default_rate_pct": 6.0, "true_default_rate_asof": "2026-04 (Fitch, incl. distressed exchanges)",
        "pik_income_share_pct": 8.0, "pik_asof": "2026-Q1 (BDC filings)",
        "redemption_gates_count": 1,
        "hyperscaler_guidance_cuts": 0,
        "oracle_cds_5y_bps": None, "oracle_cds_asof": "",
        "kr_industrial_power_yoy_pct": 70, "kr_power_asof": "2026-03 (Allianz)",
        "taiwan_tier_manual": 1,
        "sea_policy_tier_manual": 1,
        "fed_cuts_priced_2026": 1,
        "hormuz_closed_since": "2026-02-28",
        "weak_auction_count": 1,
        "pik_rising_quarters": 4,
        "last_seen_30y_auction": "",
        # v3.2: manual CAPE fallback (used only if the multpl.com scrape fails).
        # Update from https://www.multpl.com/shiller-pe or Shiller's Yale
        # spreadsheet if the auto scraper breaks.
        "cape_manual": 41.85, "cape_asof": "2026-07 (multpl.com manual)",
    }
    manual = {**manual_defaults, **prior.get("manual", {})}

    falsifiers_defaults = {
        "ceasefire_and_reopening": False,
        "hyperscaler_two_quarters_held": False,
        "true_defaults_rolling_over": False,
        "jgb_auctions_normalized": False,
    }
    falsifiers = {**falsifiers_defaults, **prior.get("falsifiers", {})}
    history = list(prior.get("history", []))

    # ---- fetch: markets (batched yfinance + Stooq fallback, 429 backoff) ----
    # One batched download for all spot symbols instead of a per-ticker burst,
    # with exponential backoff on rate-limits and a keyless Stooq fallback so a
    # single 429 no longer zeroes every downstream field.
    market_tickers = ["CL=F", "RB=F", "HO=F", "BZ=F", "JPY=X"]
    try:
        prices, yf_err, stooq_used = fetch_market_prices(market_tickers)
        crack, wti = fetch_crack_spread(prices)
        if wti:
            auto["wti"] = round(wti, 2)
        if crack is not None:
            auto["crack_spread_321"] = crack
        if prices.get("BZ=F"):
            auto["brent"] = round(prices["BZ=F"], 2)
        if prices.get("JPY=X"):
            auto["usdjpy"] = round(prices["JPY=X"], 2)
        dd = fetch_qqq_drawdown()
        if dd is not None:
            auto["qqq_drawdown_pct"] = dd

        got = sorted(prices)
        if not prices:
            head = str(yf_err).split("\n")[0][:60] if yf_err else "no data"
            status["yfinance"] = f"held-last: {head}"
            log(f"market fetch empty — holding last values ({head})")
        else:
            note = f"ok — {len(got)}/{len(market_tickers)} priced"
            if stooq_used:
                note += f"; stooq fallback: {','.join(stooq_used)}"
            if yf_err:
                note += f"; yf soft-fail: {str(yf_err).split(chr(10))[0][:40]}"
            status["yfinance"] = note
    except Exception as e:
        msg = str(e).split("\n")[0][:80]
        status["yfinance"] = f"held-last: {msg}"
        log(f"market fetch failed — holding last values ({msg})")

    # ---- fetch: holdings prices -> holdings_prices.json (powers §1B) ----
    # Separate artefact so the daily briefing reads pre-computed weights/caps
    # instead of pulling 31 quotes via web search. Never blocks the hazard
    # model: on total failure it holds the prior file and flags it.
    try:
        hp = fetch_holdings_prices()
        HOLDINGS_PATH.write_text(json.dumps(hp, indent=2))
        status["holdings"] = f"ok — {hp['coverage']}" + (
            f"; unpriced: {','.join(hp['unpriced'])}" if hp["unpriced"] else "")
        log(f"Holdings: {hp['coverage']} | portfolio ${hp['portfolio_value_usd']:,} "
            f"| US(listing) {hp['geography_listing']['US']['weight_pct']}% "
            f"| US(economic) {hp['geography_economic'].get('US', {}).get('weight_pct', 0)}%")
    except Exception as e:
        msg = str(e).split("\n")[0][:80]
        status["holdings"] = f"held-last: {msg}"
        log(f"holdings fetch failed — prior holdings_prices.json retained ({msg})")

    # ---- fetch: FRED ----
    if FRED_KEY:
        try:
            for key in ("ust10", "ust30", "breakeven10", "hy_oas", "ig_oas"):
                val, _ = fetch_fred_latest(FRED_SERIES[key])
                if val is not None:
                    auto[key] = val
            _, food_yoy, food_date = fetch_fred_yoy(FRED_SERIES["food_index"])
            if food_yoy is not None:
                auto["food_index_yoy"] = food_yoy
                auto["food_index_asof"] = food_date
            _, fert_yoy, fert_date = fetch_fred_yoy(FRED_SERIES["fertilizer_ppi"])
            if fert_yoy is not None:
                auto["fertilizer_ppi_yoy"] = fert_yoy
                auto["fertilizer_asof"] = fert_date
            # v3.2: margin debt (Fed Z.1, quarterly)
            md_lvl, md_yoy, md_date = fetch_margin_debt_yoy()
            if md_lvl is not None:
                auto["margin_debt_bn"] = md_lvl
                auto["margin_debt_yoy"] = md_yoy
                auto["margin_debt_asof"] = md_date
            status["fred"] = "ok"
        except Exception as e:
            status["fred"] = f"fail: {e}"
            log(f"FRED failed: {e}")
    else:
        status["fred"] = "no API key — holding last values"

    # ---- fetch: Shiller CAPE (multpl.com) — v3.2 ----
    try:
        cape, cape_asof = fetch_shiller_cape()
        if cape is not None:
            auto["cape_auto"] = cape
            auto["cape_auto_asof"] = cape_asof
            status["cape"] = "ok"
        else:
            status["cape"] = "parse-empty — holding manual value"
    except Exception as e:
        status["cape"] = f"fail: {e}"
        log(f"CAPE scrape failed: {e}")

    # ---- fetch: Fitch private credit default rate (lsta.org) — v3.2 ----
    # Auto-updates manual.true_default_rate_pct ONLY when the scraped
    # value's month-year is fresher than what's already in the file.
    # Preserves manual override behavior while eliminating the manual step.
    try:
        rate, month_year, post_date = fetch_fitch_private_credit_rate()
        if month_year is not None:
            current_asof = manual.get("true_default_rate_asof", "")
            new_asof = f"{month_year} (Fitch via LSTA, posted {post_date})"
            def _month_key(s):
                m2 = re.search(r"([A-Z][a-z]+)\s+(\d{4})", s)
                if not m2: return (0, 0)
                months = "January February March April May June July "\
                         "August September October November December".split()
                try:
                    return (int(m2.group(2)), months.index(m2.group(1)) + 1)
                except ValueError:
                    return (0, 0)
            if _month_key(month_year) > _month_key(current_asof):
                if rate is not None:
                    manual["true_default_rate_pct"] = rate
                    log(f"UPDATED true_default_rate: {rate}% ({month_year})")
                    status["fitch"] = f"ok — updated to {rate}% ({month_year})"
                    manual["true_default_rate_asof"] = new_asof
                else:
                    # Newer period seen but no % parsed: do NOT relabel the old
                    # rate with the new month (that hid staleness pre-v3.2b).
                    log(f"Fitch {month_year} print seen but rate not parsed — holding {manual.get('true_default_rate_pct')}%")
                    status["fitch"] = f"partial — {month_year} seen, rate not parsed; holding manual value"
            else:
                status["fitch"] = f"ok — no fresher print ({month_year} <= current)"
        else:
            status["fitch"] = "parse-empty — holding manual value"
    except Exception as e:
        status["fitch"] = f"fail: {e}"
        log(f"Fitch scrape failed: {e}")

    # ---- fetch: MoF JGB ----
    try:
        jgb = fetch_jgb()
        if jgb:
            auto.update(jgb)
            status["mof_jgb"] = "ok"
        else:
            status["mof_jgb"] = "parse-empty — holding last values"
    except Exception as e:
        status["mof_jgb"] = f"fail: {e}"
        log(f"MoF JGB failed: {e}")

    # ---- fetch: TreasuryDirect + weak-auction ratchet ----
    try:
        td = fetch_treasury_b2c()
        auto.update(td)
        new_date = td.get("bid_to_cover_30y_date", "")
        b2c30 = td.get("bid_to_cover_30y")
        if new_date and b2c30 is not None and new_date != manual.get("last_seen_30y_auction"):
            manual["last_seen_30y_auction"] = new_date
            if b2c30 < WEAK_AUCTION_B2C:
                manual["weak_auction_count"] = (manual.get("weak_auction_count") or 0) + 1
                log(f"ESCALATOR: weak 30y auction ({b2c30} < {WEAK_AUCTION_B2C}) on {new_date} "
                    f"-> weak_auction_count = {manual['weak_auction_count']}")
        status["treasury"] = "ok"
    except Exception as e:
        status["treasury"] = f"fail: {e}"
        log(f"TreasuryDirect failed: {e}")

    # ---- fetch: WHO ----
    try:
        auto["pandemic_tier"] = fetch_pandemic_tier()
        status["who"] = "ok"
    except Exception as e:
        status["who"] = f"fail: {e}"
        log(f"WHO RSS failed: {e}")

    # ---- compute hazard model (source of truth for history) ----
    model = compute_model(auto, manual, falsifiers)
    log(f"Regime: {model['regime']} | eff={model['effective_count']} | "
        f"MC={model['mc_hazard']}% | SC={model['sc_hazard']}%")

    today = f"{datetime.now(SGT):%Y-%m-%d}"
    history = [h for h in history if h.get("date") != today]
    history.append({
        "date": today,
        "effective_count": model["effective_count"],
        "mc_hazard": model["mc_hazard"],
        "sc_hazard": model["sc_hazard"],
        "regime": model["regime"],
    })
    history = history[-120:]

    # ---- freshness stamp (v3.5) ----
    # Do NOT advance `as_of` when the market feed came back held-last: `as_of`
    # is consumed downstream as the freshness of the readings (briefing R2 marks
    # STALE when as_of >24h). Advancing it on a networkless run would present
    # carried-forward market values (wti/brent/usdjpy/…) as if current. Instead
    # keep the prior stamp so staleness surfaces, and record the real run time
    # separately in `generated_at`.
    now_iso = datetime.now(SGT).isoformat(timespec="seconds")
    market_held_last = str(status.get("yfinance", "")).startswith("held-last")
    if market_held_last:
        as_of = prior.get("as_of") or now_iso
        log(f"market held-last — preserving as_of={as_of} (generated_at={now_iso})")
    else:
        as_of = now_iso

    out = {
        "schema": "bswan-v3",
        "as_of": as_of,
        "generated_at": now_iso,
        "market_stale": market_held_last,
        "fetch_status": status,
        "auto": auto,
        "manual": manual,
        "falsifiers": falsifiers,
        "computed": model,
        "history": history,
    }
    OUT_PATH.write_text(json.dumps(out, indent=2))
    log(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
