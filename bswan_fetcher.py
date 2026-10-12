#!/usr/bin/env python3
"""
Black Swan Daily Convergence Monitor — Automated Data Fetcher
=============================================================
Fetches live indicator readings from free public APIs at 7am each day,
writes  daily_readings.json  in the same directory as this script,
and the dashboard HTML loads that file on page open.

SETUP (one-time):
  pip install requests yfinance schedule

SOURCES USED (all free, no auth required except FRED):
  yfinance   — WTI crude, 10y yield proxy, MOVE proxy
  FRED API   — DGS10 (10y yield), T10YIE (breakeven), BAMLH0A0HYM2 (HY OAS)
  TreasuryDirect — latest auction bid-to-cover (scraped)
  WHO RSS    — Disease Outbreak News headlines for pandemic signal

FRED API key (free at https://fred.stlouisfed.org/docs/api/api_key.html):
  Set the environment variable  FRED_API_KEY  or paste it in FRED_KEY below.
"""

import os, sys, json, logging, datetime, time, re
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Missing: pip install requests")
try:
    import yfinance as yf
except ImportError:
    sys.exit("Missing: pip install yfinance")

# ─── CONFIG ────────────────────────────────────────────────────────────────
FRED_KEY = os.environ.get("FRED_API_KEY", "")          # paste key here if not using env var
OUT_DIR  = Path(__file__).parent                       # writes next to this script
LOG_FILE = OUT_DIR / "bswan_fetcher.log"
OUT_FILE = OUT_DIR / "daily_readings.json"
TIMEOUT  = 12                                          # seconds per request
# ────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("bswan")


# ─── HELPERS ────────────────────────────────────────────────────────────────

def safe(fn, label, default):
    """Call fn(), return default and log on any exception."""
    try:
        return fn()
    except Exception as e:
        log.warning(f"[{label}] fetch failed — using last/default: {e}")
        return default


def fred(series_id, default):
    """Fetch the latest value of a FRED series. Requires FRED_KEY."""
    if not FRED_KEY:
        log.warning(f"[FRED/{series_id}] No API key — set FRED_API_KEY env var")
        return default
    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}&api_key={FRED_KEY}&file_type=json"
        f"&sort_order=desc&limit=5"
    )
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    obs = [o for o in r.json()["observations"] if o["value"] != "."]
    return float(obs[0]["value"])


def yf_close(ticker, default):
    """Fetch latest close from yfinance."""
    t = yf.Ticker(ticker)
    hist = t.history(period="5d")
    if hist.empty:
        raise ValueError("empty history")
    return round(float(hist["Close"].iloc[-1]), 3)


def treasury_btc(default):
    """
    Pull the most recent 10y or 30y auction bid-to-cover from TreasuryDirect.
    Falls back gracefully.
    """
    url = "https://www.treasurydirect.gov/TA_WS/securities/search?type=Note&term=10-Year&pagesize=5&format=json"
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    auctions = r.json()
    # bidToCoverRatio may be null if result not yet posted
    for a in auctions:
        btc = a.get("bidToCoverRatio")
        if btc:
            return round(float(btc), 3)
    return default


def who_pheic_level():
    """
    Check WHO Disease Outbreak News RSS for PHEIC and Ebola/hantavirus keywords.
    Returns 0 (none) – 3 (PHEIC + novel transmission confirmed).
    """
    url = "https://www.who.int/rss-feeds/news-releases.xml"
    r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "bswan-monitor/1.0"})
    text = r.text.lower()
    # Scoring heuristic: keyword presence in recent headlines
    score = 0
    if any(k in text for k in ["ebola","hantavirus","marburg","mpox"]):
        score = max(score, 1)   # regional cluster
    if "public health emergency" in text or "pheic" in text:
        score = max(score, 2)   # PHEIC declared
    if ("novel" in text or "unknown transmission" in text) and score >= 2:
        score = 3               # PHEIC + novel route
    return score


def move_proxy():
    """
    MOVE index isn't on yfinance. Use ^VIX as a directional proxy.
    Real MOVE: subscribe to ICE or use Bloomberg. Map VIX to rough MOVE range.
    """
    vix = yf_close("^VIX", 20.0)
    # Rough calibration: VIX ~15 → MOVE ~100; VIX ~20 → MOVE ~120; VIX ~30 → MOVE ~155
    return round(90 + vix * 2.1, 1)


# ─── FETCH ALL ──────────────────────────────────────────────────────────────

def fetch_all():
    log.info("─── Black Swan fetch starting ──────────────────────────")
    today = datetime.date.today().isoformat()

    # Load yesterday's snapshot as fallback defaults
    prev = {}
    if OUT_FILE.exists():
        try:
            prev = json.loads(OUT_FILE.read_text())["readings"]
        except Exception:
            pass

    def p(sig, i): return prev.get(sig, {}).get(str(i), None)

    readings = {}

    # ── 1. Energy supply shock ──────────────────────────────────────────────
    log.info("Fetching: Energy")
    wti      = safe(lambda: yf_close("CL=F",    p("energy","0") or 112), "WTI",      p("energy","0") or 112)
    # Crack spread: approximate as HO (heating oil) - CL spread
    ho       = safe(lambda: yf_close("HO=F",    None), "HeatOil",  None)
    crack    = round((ho * 42 - wti), 1) if ho else (p("energy","1") or 46)  # gal→bbl conversion
    # Hormuz transits: no free real-time API; placeholder uses last saved or 5
    transits = p("energy","2") or 5   # Manual override required — see NOTE below
    be       = safe(lambda: fred("T10YIE",  p("energy","3") or 3.1), "FRED/breakeven", p("energy","3") or 3.1)
    readings["energy"] = {"0": wti, "1": crack, "2": transits, "3": round(be, 3)}
    log.info(f"  WTI={wti}  crack≈{crack}  Hormuz transits={transits}  BE={be}")

    # ── 2. Private credit ───────────────────────────────────────────────────
    log.info("Fetching: Private credit")
    # Default rates from KBRA/Proskauer are monthly/quarterly — no real-time free API.
    # HY OAS from FRED is the best liquid proxy for credit stress.
    def_rate = p("pcred","0") or 5.7   # Manual — update from KBRA DLD monthly
    pik_pct  = p("pcred","1") or 12.0  # Manual — update from BDC filings quarterly
    redeem   = p("pcred","2") or 70.0  # Manual — from BDC press releases
    oas      = safe(lambda: fred("BAMLH0A0HYM2", p("pcred","3") or 520), "FRED/HY-OAS", p("pcred","3") or 520)
    readings["pcred"] = {"0": def_rate, "1": pik_pct, "2": redeem, "3": round(oas, 1)}
    log.info(f"  default={def_rate}%  PIK={pik_pct}%  redeem={redeem}%  HY-OAS={oas}bp")

    # ── 3. Treasury / fiscal ────────────────────────────────────────────────
    log.info("Fetching: Treasury")
    y10  = safe(lambda: fred("DGS10",   p("fiscal","0") or 4.8), "FRED/10y",    p("fiscal","0") or 4.8)
    # ACM term premium not on free API; use DGS10 - T5YIE as rough proxy
    t5ie = safe(lambda: fred("T5YIE",   None),                   "FRED/T5YIE",  None)
    tp   = round(float(y10) - float(t5ie), 3) if t5ie else (p("fiscal","1") or 0.9)
    move = safe(move_proxy,                                       "MOVE-proxy",  p("fiscal","2") or 140)
    btc  = safe(lambda: treasury_btc(p("fiscal","3") or 2.25),   "TreasDirect", p("fiscal","3") or 2.25)
    readings["fiscal"] = {"0": round(y10,3), "1": tp, "2": move, "3": btc}
    log.info(f"  10y={y10}%  TP≈{tp}  MOVE-proxy≈{move}  BTC={btc}x")

    # ── 4. US–China ─────────────────────────────────────────────────────────
    log.info("Fetching: US-China (semi-static)")
    tariff = p("china","0") or 29.2   # Update from PIIE/Fitch tariff monitor weekly
    rare   = p("china","1") or 2      # 0-3 dropdown; manual
    readings["china"] = {"0": tariff, "1": rare}
    log.info(f"  tariff={tariff}%  rare-earth tier={rare}")

    # ── 5. Taiwan Strait ────────────────────────────────────────────────────
    log.info("Fetching: Taiwan Strait")
    pla = p("taiwan","0") or 120      # From Taiwan MND daily release — manual
    esc = p("taiwan","1") or 2        # Dropdown: 0-3 manual
    readings["taiwan"] = {"0": pla, "1": esc}
    log.info(f"  PLA sorties={pla}  esc-tier={esc}")

    # ── 6. Pandemic ─────────────────────────────────────────────────────────
    log.info("Fetching: Pandemic / WHO")
    who  = safe(who_pheic_level, "WHO-RSS", p("pandemic","0") or 2)
    dbl  = p("pandemic","1") or 14    # Case doubling time — from outbreak reports
    readings["pandemic"] = {"0": who, "1": dbl}
    log.info(f"  WHO tier={who}  doubling={dbl}d")

    # ── Write output ─────────────────────────────────────────────────────────
    payload = {
        "date": today,
        "fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "readings": readings,
        "notes": {
            "manual_indicators": [
                "energy.2 — Hormuz vessel transits (EIA chokepoint page)",
                "pcred.0  — Direct-lending default rate (KBRA DLD monthly)",
                "pcred.1  — PIK share of BDC income (SEC EDGAR filings)",
                "pcred.2  — BDC redemption fulfilment % (press releases)",
                "china.0  — US effective tariff on China (PIIE/Fitch monthly)",
                "china.1  — Rare-earth control tier (CSIS/Reuters)",
                "taiwan.0 — PLA aircraft count (Taiwan MND daily)",
                "taiwan.1 — Escalation tier (Taiwan MND / Reuters)",
                "pandemic.1 — Case doubling time (WHO/ECDC outbreak pages)",
            ],
            "fred_series": {
                "T10YIE": "10y breakeven inflation",
                "DGS10":  "10y nominal Treasury yield",
                "T5YIE":  "5y breakeven (used for term-premium proxy)",
                "BAMLH0A0HYM2": "ICE BofA US HY spread (OAS, basis points)",
            },
            "yfinance_tickers": {
                "CL=F": "WTI crude front-month futures",
                "HO=F": "Heating oil futures (crack spread proxy)",
                "^VIX": "CBOE VIX (MOVE index proxy)",
            },
        },
    }
    OUT_FILE.write_text(json.dumps(payload, indent=2))
    log.info(f"✓ Written → {OUT_FILE}")
    log.info("─── Fetch complete ─────────────────────────────────────")
    return payload


# ─── SCHEDULER (run as standalone daemon with  python bswan_fetcher.py --daemon) ──

def run_daemon():
    try:
        import schedule
    except ImportError:
        sys.exit("Missing: pip install schedule")

    log.info("Daemon starting — will fetch at 07:00 local time daily")
    schedule.every().day.at("07:00").do(fetch_all)

    # Run once immediately on startup so you get fresh data right away
    fetch_all()

    while True:
        schedule.run_pending()
        time.sleep(30)


# ─── ENTRY POINT ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--daemon" in sys.argv:
        run_daemon()
    else:
        # Single-shot: called by cron / Task Scheduler
        fetch_all()
