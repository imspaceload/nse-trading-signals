import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
from datetime import datetime
import pytz
import concurrent.futures
import pandas as pd
import numpy as np
import json
import difflib

import zerodha_api

from config import (
    SYMBOLS, STOP_LOSS_PCT, TARGET_PCT,
    RSI_PERIOD, RSI_OVERBOUGHT, RSI_OVERSOLD,
    EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER,
)
from data_fetcher import (
    get_spot_price, get_intraday_data, get_option_chain_data,
    get_option_recommendation, is_market_open, get_current_option_ltp,
    get_nse_indices, get_global_cues, get_chart_data, get_sparkline_data,
    get_option_chain_nse_direct, compute_option_stats, get_market_opens_in,
    _fmt_oi,
)
from indicators import (
    compute_rsi, compute_macd, compute_supertrend, compute_vwap,
    evaluate_oi, generate_signal, compute_all_signals,
    compute_support_resistance,
)
from news_scraper import scrape_moneycontrol_news
from claude_analyzer import analyze_market
from notifier import send_signal_email
from trades import (
    create_trade, close_trade, get_open_trades, get_closed_trades, delete_trade,
)
from sms_sender import (
    send_sms_to_all, get_subscribers, add_subscriber,
    remove_subscriber, get_sms_log,
    get_watchlist, add_to_watchlist, remove_from_watchlist,
)
from dhan_api import (
    get_option_chain_for_symbol, get_candles_for_symbol,
    get_spot_price_dhan, resolve_symbol, get_expiry_list,
    get_option_chain_dhan,
)

IST = pytz.timezone("Asia/Kolkata")

# ── Symbol aliases and display names ──
SYMBOL_ALIASES = {
    "NIFTY":       "NIFTY 50",
    "NIFTY50":     "NIFTY 50",
    "BANKNIFTY":   "BANK NIFTY",
    "NIFTYNEXT50": "NIFTY NEXT 50",
    "INFY":        "INFOSYS",
    "HDFCBANK":    "HDFC BANK",
    "ICICIBANK":   "ICICI BANK",
    "MM":          "M&M",
    "BAJAJAUTO":   "BAJAJ-AUTO",
    "FINNIFTY":    "NIFTY 50",  # map to NIFTY 50 for now since not in SYMBOLS
}

# Short display names for watchlist
SYMBOL_SHORT = {
    "NIFTY 50":   ("NIFTY50",   "Nifty 50 Index",     "^NSEI"),
    "BANK NIFTY": ("BANKNIFTY", "Nifty Bank Index",    "^NSEBANK"),
    "RELIANCE":   ("RELIANCE",  "Reliance Industries", "RELIANCE.NS"),
    "HDFC BANK":  ("HDFCBANK",  "HDFC Bank",           "HDFCBANK.NS"),
    "TCS":        ("TCS",       "Tata Consultancy",    "TCS.NS"),
    "INFOSYS":    ("INFY",      "Infosys",             "INFY.NS"),
    "IDEA":       ("IDEA",      "Vodafone Idea",       "IDEA.NS"),
    "SBIN":       ("SBIN",      "State Bank of India", "SBIN.NS"),
    "ICICI BANK": ("ICICIBANK", "ICICI Bank",          "ICICIBANK.NS"),
    "ITC":        ("ITC",       "ITC Limited",         "ITC.NS"),
    "ZOMATO":     ("ZOMATO",    "Zomato",              "ZOMATO.NS"),
    "TATAMOTORS": ("TATAMOTORS","Tata Motors",         "TATAMOTORS.NS"),
}

st.set_page_config(
    page_title="Options Terminal",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ═══════════════════════════════════════════════
#  Zerodha Kite Connect — OAuth handler + token restore
# ═══════════════════════════════════════════════

# Try to restore today's saved token on every cold start
if "kite_restore_attempted" not in st.session_state:
    st.session_state.kite_restore_attempted = True
    zerodha_api.restore_saved_token()

# Handle Zerodha OAuth redirect: ?request_token=xxx&action=login
_qp = st.query_params
if _qp.get("action") == "login" and _qp.get("request_token"):
    _rt = _qp["request_token"]
    _tok = zerodha_api.complete_login(_rt)
    if _tok:
        st.session_state["kite_just_connected"] = True
    # Clear query params so it doesn't re-run on refresh
    st.query_params.clear()
    st.rerun()

import os as _os
kite_configured = bool(_os.environ.get("KITE_API_KEY","").strip() and _os.environ.get("KITE_API_SECRET","").strip())
kite_live = zerodha_api.is_connected() if kite_configured else False

_refresh_ms = 15_000 if is_market_open() else 300_000
st_autorefresh(interval=_refresh_ms, limit=0, key="live_refresh")

# ═══════════════════════════════════════════════
#  CSS — Dark Terminal Theme
# ═══════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
* { font-family: 'Inter', -apple-system, sans-serif !important; box-sizing: border-box; }

/* ── Base ── */
.block-container { padding: 0 !important; max-width: 100% !important; }
section[data-testid="stMain"] > div { padding: 0 !important; }
html, body, [data-testid="stAppViewContainer"] { background: #0e0e1a !important; }

/* ── Hide Streamlit chrome ── */
#MainMenu, footer, .stDeployButton, [data-testid="manage-app-button"] { display: none !important; }
header[data-testid="stHeader"] { background: transparent !important; height: 0 !important; min-height: 0 !important; visibility: hidden !important; }
div[data-testid="stSidebar"] { display: none !important; }
button[data-testid="stSidebarCollapsedControl"] { display: none !important; }
[data-testid="stDecoration"] { display: none !important; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: #0e0e1a; }
::-webkit-scrollbar-thumb { background: #2a2a4a; border-radius: 3px; }

/* ── Tabs ── */
button[data-baseweb="tab"] {
    background: transparent !important;
    border: none !important;
    border-bottom: 2px solid transparent !important;
    color: #6b7280 !important;
    font-size: 0.9em !important;
    font-weight: 500 !important;
    padding: 10px 18px !important;
    transition: color 0.2s !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
    border-bottom: 2px solid #387ed1 !important;
    color: #e8e8e8 !important;
    font-weight: 600 !important;
}
div[data-testid="stTabsTabList"] {
    border-bottom: 1px solid #2a2a4a !important;
    gap: 0 !important;
    padding: 0 4px !important;
}
[data-testid="stTabsContent"] { padding: 12px 4px !important; }

/* ── Left panel watchlist buttons — Zerodha flat row style ── */
div[data-testid="column"]:first-child [data-testid="stButton"] button {
    background: transparent !important;
    border: none !important;
    border-bottom: 1px solid rgba(42,42,74,0.4) !important;
    border-radius: 0 !important;
    color: #e2e8f0 !important;
    font-size: 0.83em !important;
    font-weight: 600 !important;
    padding: 7px 8px 4px 8px !important;
    text-align: left !important;
    width: 100% !important;
    letter-spacing: 0.2px !important;
    transition: background 0.1s !important;
    box-shadow: none !important;
}
div[data-testid="column"]:first-child [data-testid="stButton"] button:hover {
    background: rgba(56,126,209,0.07) !important;
    color: #fff !important;
}
/* × delete button */
div[data-testid="column"]:first-child + div[data-testid="column"] [data-testid="stButton"] button {
    background: transparent !important;
    border: none !important;
    border-radius: 0 !important;
    color: #4b5563 !important;
    font-size: 0.85em !important;
    padding: 4px 2px !important;
    min-height: 0 !important;
    box-shadow: none !important;
}
div[data-testid="column"]:first-child + div[data-testid="column"] [data-testid="stButton"] button:hover {
    color: #ef4444 !important;
    background: transparent !important;
}

/* ── Radio as button group (timeframe/chart type) ── */
div[data-testid="stRadio"] > div {
    flex-direction: row !important;
    gap: 1px !important;
    flex-wrap: nowrap !important;
    background: #12121f;
    border: 1px solid #2a2a4a;
    border-radius: 6px;
    padding: 3px;
    display: inline-flex !important;
}
div[data-testid="stRadio"] > div > label {
    background: transparent !important;
    border: none !important;
    border-radius: 4px !important;
    color: #6b7280 !important;
    cursor: pointer !important;
    font-size: 0.78em !important;
    font-weight: 500 !important;
    padding: 4px 10px !important;
    white-space: nowrap !important;
    transition: all 0.15s !important;
    margin: 0 !important;
}
div[data-testid="stRadio"] > div > label:has(input:checked) {
    background: #1e293b !important;
    color: #e8e8e8 !important;
    font-weight: 600 !important;
}
div[data-testid="stRadio"] > div > label > div:first-child { display: none !important; }
div[data-testid="stRadio"] label p { margin: 0 !important; font-size: inherit !important; }

/* ── Inputs ── */
[data-testid="stTextInput"] input {
    background: #12121f !important;
    border: 1px solid #2a2a4a !important;
    border-radius: 6px !important;
    color: #e8e8e8 !important;
    font-size: 0.85em !important;
    padding: 6px 10px !important;
}
[data-testid="stTextInput"] input::placeholder { color: #4b5563 !important; }
[data-testid="stTextInput"] input:focus { border-color: #387ed1 !important; }

/* ── Selectbox ── */
[data-testid="stSelectbox"] div[data-baseweb="select"] > div:first-child {
    background: #12121f !important;
    border: 1px solid #2a2a4a !important;
    border-radius: 6px !important;
    color: #e8e8e8 !important;
    font-size: 0.85em !important;
    min-height: 34px !important;
}

/* ── Buttons (primary = accent) ── */
button[kind="primary"] {
    background: #387ed1 !important;
    border: none !important;
    border-radius: 6px !important;
    color: white !important;
    font-weight: 600 !important;
}
button[kind="secondary"] {
    background: #12121f !important;
    border: 1px solid #2a2a4a !important;
    border-radius: 6px !important;
    color: #d1d5db !important;
}

/* ── Alert/Warning ── */
[data-testid="stAlert"] {
    background: #1a1a2e !important;
    border: 1px solid #2a2a4a !important;
    border-radius: 6px !important;
    color: #9ca3af !important;
    font-size: 0.85em !important;
    padding: 10px 14px !important;
}

/* ── Caption ── */
.stCaption p { color: #4b5563 !important; font-size: 0.75em !important; }

/* ── Spinner ── */
[data-testid="stSpinner"] { color: #387ed1 !important; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════
#  Session State Defaults
# ═══════════════════════════════════════════════
if "active_symbol" not in st.session_state:
    st.session_state.active_symbol = "NIFTY 50"
if "chart_tf" not in st.session_state:
    st.session_state.chart_tf = "1D"
if "chart_type" not in st.session_state:
    st.session_state.chart_type = "Candles"
if "news_filter" not in st.session_state:
    st.session_state.news_filter = "All"
if "_wl_selected" not in st.session_state:
    st.session_state._wl_selected = None


# ═══════════════════════════════════════════════
#  Helper Functions
# ═══════════════════════════════════════════════

def _make_sym(name: str) -> dict:
    n = name.strip().upper()
    INDEX_YF = {"NIFTY": "^NSEI", "NIFTY50": "^NSEI", "BANKNIFTY": "^NSEBANK", "SENSEX": "^BSESN"}
    yf_sym = INDEX_YF.get(n, f"{n}.NS")
    return {"yf": yf_sym, "nse": n, "tv": f"NSE:{n}"}


def _find_symbol_candidates(query: str) -> list:
    q = query.strip().upper()
    if not q:
        return []
    seen, results = set(), []

    def _add(k):
        if k not in seen:
            seen.add(k)
            results.append(k)

    for k in SYMBOLS:
        if q == k.upper() or q == SYMBOLS[k].get("nse", "").upper():
            _add(k)
    if results:
        return results

    if q in SYMBOL_ALIASES:
        alias = SYMBOL_ALIASES[q]
        for k in SYMBOLS:
            if k == alias:
                _add(k)
    if results:
        return results

    for k in SYMBOLS:
        nse = SYMBOLS[k].get("nse", "").upper()
        if k.upper().startswith(q) or nse.startswith(q):
            _add(k)
    for k in SYMBOLS:
        nse = SYMBOLS[k].get("nse", "").upper()
        if q in k.upper() or q in nse:
            _add(k)
    if results:
        return results[:10]

    if len(q) >= 2:
        n = len(q)
        tmap: dict = {}
        for k in SYMBOLS:
            tmap.setdefault(k.upper()[:n], []).append(k)
            nse = SYMBOLS[k].get("nse", "").upper()
            if nse:
                tmap.setdefault(nse[:n], []).append(k)
        for c in difflib.get_close_matches(q, list(tmap.keys()), n=6, cutoff=0.6):
            for k in tmap[c]:
                _add(k)
    return results[:10]


def _atm_strike(price: float) -> int:
    if price <= 0:
        return 0
    if price < 50:     step = 2.5
    elif price < 250:  step = 5
    elif price < 1000: step = 10
    elif price < 5000: step = 50
    else:              step = 100
    return int(round(price / step) * step)


def make_sparkline(prices: list, color: str = "#4caf50", w: int = 72, h: int = 26) -> str:
    if not prices or len(prices) < 2:
        return f'<svg width="{w}" height="{h}"></svg>'
    lo, hi = min(prices), max(prices)
    if hi == lo:
        hi = lo + 0.01
    pts = []
    n = len(prices) - 1
    for i, p in enumerate(prices):
        x = round(i * w / n, 1)
        y = round((1 - (p - lo) / (hi - lo)) * (h - 2) + 1, 1)
        pts.append(f"{x},{y}")
    path = " ".join(pts)
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" style="overflow:visible">'
        f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="1.5" stroke-linejoin="round"/>'
        f'</svg>'
    )


def _pct_color(pct: float) -> str:
    return "#4caf50" if pct >= 0 else "#f44336"


def _news_sentiment(headline: str) -> dict:
    text = headline.lower()
    bull_kw = ["gain", "rise", "rally", "up", "surge", "positive", "growth", "beat", "strong",
               "high", "buy", "bull", "bullish", "recover", "boost", "jump", "soar"]
    bear_kw = ["fall", "drop", "decline", "down", "loss", "weak", "miss", "crash", "cut",
               "sell", "bear", "bearish", "concern", "worry", "slump", "plunge", "dip"]
    hi_kw   = ["rbi", "fed", "rate", "gdp", "inflation", "budget", "election", "war",
               "crisis", "policy", "sebi", "fii", "ipo", "quarterly", "earnings"]

    bull_sc = sum(1 for k in bull_kw if k in text)
    bear_sc = sum(1 for k in bear_kw if k in text)
    high_impact = any(k in text for k in hi_kw)

    sentiment = "BULLISH" if bull_sc > bear_sc else ("BEARISH" if bear_sc > bull_sc else "NEUTRAL")
    impact = "HIGH IMPACT" if high_impact else ("MEDIUM IMPACT" if (bull_sc + bear_sc) >= 2 else "LOW IMPACT")
    return {"sentiment": sentiment, "impact": impact}


def _ai_action(headline: str) -> str:
    h = headline.lower()
    if "rbi" in h and ("rate" in h or "policy" in h):
        return "Monitor rate-sensitive sectors — banking, NBFCs, autos may react sharply."
    if "inflation" in h:
        return "Inflation data could pressure RBI stance. Watch bond yields and NBFC stocks."
    if "fii" in h and ("buy" in h or "inflow" in h):
        return "FII inflows support index. Track large-cap momentum and index options."
    if "result" in h or "quarter" in h or "earnings" in h:
        return "Post-results volatility likely. Monitor IV crush and ATM strikes."
    if "crude" in h or "oil" in h:
        return "Oil move impacts OMCs, airlines, paint cos. Hedge or trade the sector."
    return "Monitor related stocks for breakout / breakdown setups in next session."


def _market_sentiment_score(rsi_val, pcr, st_dir, vwap_sig) -> int:
    score = 0
    score += min(25, max(0, int((rsi_val - 30) / 40 * 25)))
    score += min(25, max(0, int(pcr * 25)))
    score += 25 if st_dir == 1 else 0
    score += 25 if vwap_sig == "BUY" else 0
    return min(100, max(0, score))


# ═══════════════════════════════════════════════
#  Cached Data Loaders
# ═══════════════════════════════════════════════

_mkt_open_now = is_market_open()

@st.cache_data(ttl=45 if _mkt_open_now else 300)
def _load_indices():
    return get_nse_indices()

@st.cache_data(ttl=90 if _mkt_open_now else 600)
def _load_global_cues():
    return get_global_cues()

@st.cache_data(ttl=600)
def _load_news():
    return scrape_moneycontrol_news()

@st.cache_data(ttl=30 if _mkt_open_now else 300)
def _load_wl_prices(symbols_tuple):
    results = {}
    def _f(name):
        try:
            sym_info = SYMBOLS.get(name, _make_sym(name))
            nse_s = sym_info.get("nse", "")
            p = get_spot_price(sym_info["yf"], nse_s)
            return name, p
        except Exception:
            return name, None
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(_f, n) for n in symbols_tuple]
        for fut in concurrent.futures.as_completed(futs, timeout=10):
            try:
                n, p = fut.result()
                results[n] = p
            except Exception:
                pass
    return results

@st.cache_data(ttl=300)
def _load_sparklines(symbols_tuple):
    results = {}
    def _f(name):
        try:
            sym_info = SYMBOLS.get(name, _make_sym(name))
            return name, get_sparkline_data(sym_info["yf"])
        except Exception:
            return name, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(_f, n) for n in symbols_tuple]
        for fut in concurrent.futures.as_completed(futs, timeout=15):
            try:
                n, pts = fut.result()
                results[n] = pts
            except Exception:
                pass
    return results

@st.cache_data(ttl=20 if _mkt_open_now else 300)
def _load_symbol_data(yf_sym, nse_sym, timeframe):
    period, interval = {"1m":("1d","1m"), "3m":("1d","2m"), "5m":("1d","5m"),
                        "15m":("5d","15m"), "1h":("5d","60m"), "1D":("1mo","1d")}.get(timeframe, ("1d","5m"))
    spot, df, oi = None, pd.DataFrame(), None
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            pf   = ex.submit(get_spot_price, yf_sym, nse_sym)
            df_f = ex.submit(get_intraday_data, yf_sym, period, interval)
            oi_f = ex.submit(get_option_chain_data, nse_sym) if nse_sym else None
            spot = pf.result(timeout=10)
            df   = df_f.result(timeout=10)
            oi   = oi_f.result(timeout=8) if oi_f else None
    except Exception:
        pass
    return spot, df if df is not None else pd.DataFrame(), oi

@st.cache_data(ttl=120 if _mkt_open_now else 600)
def _load_option_chain_nse(nse_sym):
    return get_option_chain_nse_direct(nse_sym)


# ═══════════════════════════════════════════════
#  Resolve active symbol
# ═══════════════════════════════════════════════
# If watchlist click happened, apply it
if st.session_state._wl_selected:
    st.session_state.active_symbol = st.session_state._wl_selected
    st.session_state._wl_selected = None

# Determine sym dict for active symbol
active_sym_key = st.session_state.active_symbol
if active_sym_key in SYMBOLS:
    active_sym = SYMBOLS[active_sym_key]
else:
    active_sym = _make_sym(active_sym_key)


# ═══════════════════════════════════════════════
#  TOP BAR: Market Status + Indices
# ═══════════════════════════════════════════════
indices_data = _load_indices()

def _idx_pill(label: str, key: str) -> str:
    d = indices_data.get(key, {})
    if not d or not d.get("price"):
        return f'<span style="color:#4b5563;font-size:0.78em;white-space:nowrap;">{label} --</span>'
    p   = d["price"]
    pct = d.get("pct", 0)
    c   = _pct_color(pct)
    sgn = "+" if pct >= 0 else ""
    return (
        f'<span style="color:#9ca3af;font-size:0.72em;margin-right:4px;">{label}</span>'
        f'<span style="color:#e8e8e8;font-weight:600;font-size:0.82em;">{p:,.2f}</span>'
        f'<span style="color:{c};font-size:0.72em;margin-left:4px;">{sgn}{pct:.2f}%</span>'
    )

now_ist = datetime.now(IST)
mkt_open = is_market_open()
mkt_color = "#ef4444" if not mkt_open else "#4caf50"
mkt_text  = "MARKET CLOSED" if not mkt_open else "MARKET OPEN"

_data_badge = (
    '<span style="background:#7c3aed;color:white;padding:2px 8px;border-radius:20px;'
    'font-size:0.6em;font-weight:700;flex-shrink:0;">⚡ LIVE · Kite</span>'
    if kite_live else
    '<span style="background:#374151;color:#9ca3af;padding:2px 8px;border-radius:20px;'
    'font-size:0.6em;font-weight:600;flex-shrink:0;">15m delay · Yahoo</span>'
)
top_html = f"""
<div style="background:#141428;border-bottom:1px solid #2a2a4a;padding:6px 14px;
            display:flex;align-items:center;gap:18px;overflow-x:auto;white-space:nowrap;min-height:36px;">
  <span style="background:{mkt_color};color:white;padding:2px 10px;border-radius:20px;
               font-size:0.65em;font-weight:700;flex-shrink:0;">● {mkt_text}</span>
  {_data_badge}
  <span style="display:flex;gap:4px;align-items:center;">{_idx_pill("NIFTY", "NIFTY 50")}</span>
  <span style="color:#2a2a4a;">│</span>
  <span style="display:flex;gap:4px;align-items:center;">{_idx_pill("BANK", "BANK NIFTY")}</span>
  <span style="color:#2a2a4a;">│</span>
  <span style="display:flex;gap:4px;align-items:center;">{_idx_pill("FIN", "FIN NIFTY")}</span>
  <span style="color:#2a2a4a;">│</span>
  <span style="display:flex;gap:4px;align-items:center;">{_idx_pill("MIDCAP", "MIDCAP SELECT")}</span>
  <span style="color:#2a2a4a;">│</span>
  <span style="display:flex;gap:4px;align-items:center;">{_idx_pill("VIX", "INDIA VIX")}</span>
</div>
"""
st.markdown(top_html, unsafe_allow_html=True)


# ═══════════════════════════════════════════════
#  MAIN LAYOUT: Left panel + Right panel
# ═══════════════════════════════════════════════
left_col, right_col = st.columns([6, 20])


# ══════════════════════════════════════════════════════════
#  LEFT COLUMN — Logo · Global Cues · Watchlist
# ══════════════════════════════════════════════════════════
with left_col:
    st.markdown(f"""
    <div style="padding:10px 12px 8px 12px;border-bottom:1px solid #2a2a4a;background:#141428;">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div>
          <span style="color:#e8e8e8;font-size:1.0em;font-weight:700;">Options Terminal</span><br>
          <span style="color:#4b5563;font-size:0.62em;">NSE · BSE · MCX</span>
        </div>
        <span style="background:{mkt_color};color:white;padding:2px 8px;border-radius:2px;
                     font-size:0.6em;font-weight:700;">{("CLOSED" if not mkt_open else "LIVE")}</span>
      </div>
      <div style="display:flex;justify-content:space-between;margin-top:6px;">
        <div>
          <div style="color:#6b7280;font-size:0.58em;text-transform:uppercase;letter-spacing:1px;">NOW (IST)</div>
          <div style="color:#e8e8e8;font-size:0.82em;font-weight:600;">{now_ist.strftime("%-d %b · %I:%M")}<br><span style="font-size:0.85em;">{now_ist.strftime("%p")}</span></div>
        </div>
        <div style="text-align:right;">
          <div style="color:#6b7280;font-size:0.58em;text-transform:uppercase;letter-spacing:1px;">{"OPENS IN" if not mkt_open else "CLOSES IN"}</div>
          <div style="color:#f59e0b;font-size:0.85em;font-weight:600;">{get_market_opens_in()}</div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Watchlist ──
    saved_watchlist = get_watchlist()
    if not saved_watchlist:
        defaults = ["NIFTY 50", "BANK NIFTY", "RELIANCE", "HDFC BANK", "TCS", "INFOSYS", "IDEA"]
        for d in defaults:
            add_to_watchlist(d)
        saved_watchlist = get_watchlist()

    wl_prices    = _load_wl_prices(tuple(saved_watchlist))    if saved_watchlist else {}
    wl_sparklines = _load_sparklines(tuple(saved_watchlist))  if saved_watchlist else {}
    active_alerts = sum(1 for t in get_open_trades())

    # ── Watchlist header ──
    st.markdown(f"""
<div style="padding:7px 10px 5px 10px;border-bottom:1px solid #2a2a4a;
            display:flex;justify-content:space-between;align-items:center;">
  <span style="color:#6b7280;font-size:0.58em;text-transform:uppercase;letter-spacing:1px;font-weight:600;">WATCHLIST 1</span>
  <span style="color:#4b5563;font-size:0.58em;">{len(saved_watchlist)} of 250</span>
</div>""", unsafe_allow_html=True)

    # ── Search bar ──
    sym_search = st.text_input(
        "Search", placeholder="Search eg. NIFTY, RELIANCE...",
        key="wl_search", label_visibility="collapsed",
    )
    if sym_search.strip():
        candidates = _find_symbol_candidates(sym_search.strip())
        if len(candidates) == 1:
            st.session_state.active_symbol = candidates[0]
            st.rerun()
        elif len(candidates) > 1:
            sel = st.selectbox("Select", candidates, key="search_pick", label_visibility="collapsed")
            if st.button("Load", key="load_search", use_container_width=True):
                st.session_state.active_symbol = sel
                st.rerun()

    # ── Watchlist items — Zerodha style ──
    for wl_name in saved_watchlist:
        sym_info  = SYMBOLS.get(wl_name, {})
        nse_s     = sym_info.get("nse", wl_name)
        disp      = SYMBOL_SHORT.get(wl_name, (nse_s, wl_name, ""))[0]
        full_name = SYMBOL_SHORT.get(wl_name, ("", wl_name, ""))[1]
        p         = wl_prices.get(wl_name)
        spark_pts = wl_sparklines.get(wl_name, [])

        if p:
            price_str = f"{p:,.2f}"
            prev      = spark_pts[0] if spark_pts else p
            pct_chg   = round((p - prev) / prev * 100, 2) if prev else 0
            pct_str   = f"{'+'if pct_chg>=0 else ''}{pct_chg:.2f}%"
            clr       = _pct_color(pct_chg)
        else:
            price_str, pct_str, clr = "--", "--", "#6b7280"

        spark_svg  = make_sparkline(spark_pts, color=clr, w=60, h=22) if spark_pts else ""
        is_active  = (wl_name == active_sym_key)
        left_bar   = "3px solid #387ed1" if is_active else "3px solid transparent"
        row_bg     = "rgba(56,126,209,0.06)" if is_active else "transparent"

        # Row: symbol · price  |  × button
        r_cols = st.columns([11, 1])
        with r_cols[0]:
            if st.button(
                f"{disp}　　{price_str}",
                key=f"wl_{wl_name}",
                use_container_width=True,
            ):
                st.session_state._wl_selected = wl_name
                st.rerun()
        with r_cols[1]:
            if st.button("×", key=f"wl_del_{wl_name}"):
                remove_from_watchlist(wl_name)
                st.rerun()

        # Detail row: full name · sparkline · %change
        st.markdown(
            f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f'padding:0 4px 6px 4px;border-left:{left_bar};background:{row_bg};">'
            f'<span style="color:#4b5563;font-size:0.65em;">{full_name}</span>'
            f'<span style="display:flex;align-items:center;gap:5px;">'
            f'{spark_svg}'
            f'<span style="color:{clr};font-size:0.7em;font-weight:600;">{pct_str}</span>'
            f'</span></div>',
            unsafe_allow_html=True,
        )

    # ── Add symbol ──
    wl_input = st.text_input(
        "Add", placeholder="+ IDEA   or   - COFORGE",
        key="wl_input", label_visibility="collapsed",
    )
    if wl_input.strip():
        inp = wl_input.strip()
        if inp.startswith("-"):
            remove_from_watchlist(inp.lstrip("- ").upper())
            st.rerun()
        else:
            sym_to_add = inp.lstrip("+ ").upper()
            candidates = _find_symbol_candidates(sym_to_add)
            add_to_watchlist(candidates[0] if candidates else sym_to_add)
            st.rerun()


# ══════════════════════════════════════════════════════════
#  RIGHT COLUMN — Main Content
# ══════════════════════════════════════════════════════════
with right_col:
    email_on = bool(EMAIL_SENDER and EMAIL_RECEIVER)

    # ── Load data for active symbol ──
    with st.spinner(f"Loading {active_sym_key}..."):
        try:
            spot_price, df, oi_raw = _load_symbol_data(
                active_sym["yf"], active_sym.get("nse", ""),
                st.session_state.chart_tf,
            )
        except Exception as e:
            spot_price, df, oi_raw = None, pd.DataFrame(), None

    data_ok = (spot_price is not None) and (not df.empty)

    # Compute indicators when data is available
    if data_ok:
        try:
            rsi_d       = compute_rsi(df)
            macd_d      = compute_macd(df)
            st_d        = compute_supertrend(df)
            vwap_d      = compute_vwap(df)
            oi_d        = evaluate_oi(oi_raw)
            signal      = generate_signal(rsi_d, macd_d, st_d, vwap_d, oi_d, spot_price)
            all_signals = compute_all_signals(df, st.session_state.chart_tf)
            action      = signal["action"]

            # Option recommendation
            option_rec = None
            nse_sym = active_sym.get("nse", "")
            if action in ("BUY", "SELL") and nse_sym:
                try:
                    option_rec = get_option_recommendation(nse_sym, spot_price, action)
                except Exception:
                    pass

            # ── Auto signal → trade → SMS (15-min cooldown) ──
            alert_key   = f"last_auto_signal_{active_sym_key}"
            cooldown_key = f"last_signal_time_{active_sym_key}"
            last_auto   = st.session_state.get(alert_key)
            last_sig_t  = st.session_state.get(cooldown_key)
            cooldown_ok = True
            if last_sig_t:
                elapsed = (datetime.now(IST) - last_sig_t).total_seconds()
                cooldown_ok = elapsed >= 900

            sms_sent_this_run = False
            sms_sent_count = 0

            if action in ("BUY", "SELL") and action != last_auto and cooldown_ok and is_market_open():
                st.session_state[alert_key]   = action
                st.session_state[cooldown_key] = datetime.now(IST)
                opt_t = "CE" if action == "BUY" else "PE"
                if option_rec:
                    auto_trade = create_trade(
                        instrument=active_sym_key, strike=option_rec["strike"],
                        option_type=opt_t, expiry=option_rec["expiry"],
                        entry_price=option_rec["ltp"],
                        target_price=option_rec["premium_target"],
                        stop_loss=option_rec["premium_sl"], quantity=1,
                        lot_size=option_rec["lot_size"],
                    )
                    auto_trade["averaging_price"] = option_rec.get("premium_avg", round(option_rec["ltp"] * 0.7, 2))
                else:
                    auto_trade = create_trade(
                        instrument=active_sym_key,
                        strike=round(spot_price / 100) * 100,
                        option_type=opt_t, expiry="Weekly",
                        entry_price=spot_price,
                        target_price=signal["target"] or round(spot_price * 1.01, 2),
                        stop_loss=signal["stop_loss"] or round(spot_price * 0.997, 2),
                        quantity=1, lot_size=1,
                    )
                results = send_sms_to_all(auto_trade, action="BUY")
                sms_sent_count = sum(1 for r in results if r.get("status") != "failed") if results else 0
                sms_sent_this_run = True
                if email_on:
                    send_signal_email(EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER, active_sym_key, signal, option_rec)
                alert_msg = f"{action} {active_sym_key} @₹{spot_price:,.0f}"
                components.html(f"""
<script>
var ctx = new (window.AudioContext || window.webkitAudioContext)();
function beep(f,d){{var o=ctx.createOscillator();o.type='sine';o.frequency.value=f;o.connect(ctx.destination);o.start();setTimeout(()=>o.stop(),d);}}
beep({'880' if action=='BUY' else '440'},300);
setTimeout(()=>beep({'880' if action=='BUY' else '440'},300),400);
setTimeout(()=>beep({'1100' if action=='BUY' else '330'},500),800);
</script>""", height=0)

            # ── Auto-close trades ──
            for t in get_open_trades():
                t_sym = SYMBOLS.get(t["instrument"], {})
                t_nse = t_sym.get("nse", "")
                if not t_nse:
                    continue
                cur_ltp = get_current_option_ltp(t_nse, t["strike"], t["option_type"], t["expiry"])
                if cur_ltp is None:
                    continue
                if t["stop_loss"] > 0 and cur_ltp <= t["stop_loss"]:
                    closed = close_trade(t["id"], cur_ltp)
                    if closed:
                        send_sms_to_all(closed, action="EXIT")
                elif t["target_price"] > 0 and cur_ltp >= t["target_price"]:
                    closed = close_trade(t["id"], cur_ltp)
                    if closed:
                        send_sms_to_all(closed, action="EXIT")

        except Exception as e:
            action = "HOLD"
            signal = {"action": "HOLD", "buy_count": 0, "sell_count": 0, "target": None, "stop_loss": None}
            rsi_d = macd_d = st_d = vwap_d = oi_d = None
            option_rec = None
            all_signals = []
            sms_sent_this_run = False
            sms_sent_count = 0

    # ── Symbol Header ──
    if data_ok:
        day_chg = df["Close"].iloc[-1] - df["Open"].iloc[0]
        day_pct = (day_chg / df["Open"].iloc[0]) * 100
        chg_color = _pct_color(day_pct)
        arrow = "▲" if day_chg >= 0 else "▼"
        disp_short = SYMBOL_SHORT.get(active_sym_key, (active_sym_key, "", ""))[0]
        disp_full  = SYMBOL_SHORT.get(active_sym_key, ("", active_sym_key, ""))[1]
        subtitle = "NSE · INDEX" if active_sym.get("nse", "").upper() in ("NIFTY","BANKNIFTY","FINNIFTY") else "NSE"

        sym_header_html = f"""
        <div style="display:flex;justify-content:space-between;align-items:flex-start;
                    padding:8px 4px 10px 4px;border-bottom:1px solid #2a2a4a;margin-bottom:4px;">
          <div>
            <div style="display:flex;align-items:baseline;gap:8px;">
              <span style="color:#e8e8e8;font-size:1.3em;font-weight:700;">{disp_short}</span>
              <span style="color:#6b7280;font-size:0.72em;">{subtitle}</span>
            </div>
            <div style="margin-top:2px;display:flex;align-items:baseline;gap:8px;">
              <span style="color:#e8e8e8;font-size:1.6em;font-weight:700;">{spot_price:,.2f}</span>
              <span style="color:{chg_color};font-size:0.9em;font-weight:600;">
                {arrow} {abs(day_chg):,.2f} ({'+' if day_pct>=0 else ''}{day_pct:.2f}%)
              </span>
            </div>
          </div>
          <div style="text-align:right;padding-top:4px;">
            <div style="color:#6b7280;font-size:0.62em;">O: {df['Open'].iloc[0]:,.2f} &nbsp; H: {df['High'].max():,.2f} &nbsp; L: {df['Low'].min():,.2f}</div>
            {"<div style='margin-top:4px;background:#1a3a2a;color:#4caf50;padding:2px 8px;border-radius:4px;font-size:0.7em;font-weight:700;display:inline-block;'>▲ "+action+"</div>" if action=="BUY" else "<div style='margin-top:4px;background:#3a1a1a;color:#ef4444;padding:2px 8px;border-radius:4px;font-size:0.7em;font-weight:700;display:inline-block;'>▼ "+action+"</div>" if action=="SELL" else "<div style='margin-top:4px;background:#1a1a2e;color:#9ca3af;padding:2px 8px;border-radius:4px;font-size:0.7em;font-weight:600;display:inline-block;'>⏸ HOLD</div>"}
          </div>
        </div>
        """
        st.markdown(sym_header_html, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="padding:8px 4px 10px 4px;border-bottom:1px solid #2a2a4a;margin-bottom:4px;">
          <span style="color:#e8e8e8;font-size:1.2em;font-weight:700;">{active_sym_key}</span>
          <span style="color:#f59e0b;font-size:0.82em;margin-left:10px;">⟳ Loading data...</span>
        </div>
        """, unsafe_allow_html=True)

    # ── Timeframe + Chart type (above tabs) ──
    tf_col, ct_col, spacer = st.columns([3, 2, 3])
    with tf_col:
        new_tf = st.radio(
            "tf", ["1m", "3m", "5m", "15m", "1h", "1D"],
            index=["1m","3m","5m","15m","1h","1D"].index(st.session_state.chart_tf),
            horizontal=True, key="tf_radio", label_visibility="collapsed",
        )
        if new_tf != st.session_state.chart_tf:
            st.session_state.chart_tf = new_tf
            st.cache_data.clear()
            st.rerun()
    with ct_col:
        new_ct = st.radio(
            "ct", ["Candles", "Line", "Area"],
            index=["Candles","Line","Area"].index(st.session_state.chart_type),
            horizontal=True, key="ct_radio", label_visibility="collapsed",
        )
        if new_ct != st.session_state.chart_type:
            st.session_state.chart_type = new_ct
            st.rerun()

    # ── Tabs ──
    news_data = _load_news()
    news_count = len(news_data)
    tab_labels = ["Chart", "Option Chain", f"AI News {'  ' if not news_count else str(news_count)}", "SMS Admin"]
    tab_chart, tab_oc, tab_news, tab_sms = st.tabs(["Chart", "Option Chain", f"AI News  {news_count}", "SMS Admin"])


    # ══════════════════════════════════════════
    #  TAB 1: CHART
    # ══════════════════════════════════════════
    with tab_chart:
        if not data_ok or df.empty:
            st.warning(f"Chart data unavailable for {active_sym_key}. The market may be closed or data source temporarily down. Will auto-retry.")
        else:
            # Compute S/R
            @st.cache_data(ttl=300)
            def _pivot_df(yf_sym):
                return get_intraday_data(yf_sym, "5d", "15m")
            pivot_df_data = _pivot_df(active_sym["yf"])
            sr = compute_support_resistance(pivot_df_data if not pivot_df_data.empty else df)

            # Build candle data
            candle_data, vol_data = [], []
            for idx, row in df.iterrows():
                ts = int(idx.timestamp()) if hasattr(idx, "timestamp") else 0
                candle_data.append({"time": ts, "open": round(float(row["Open"]), 2),
                                     "high": round(float(row["High"]), 2),
                                     "low": round(float(row["Low"]), 2),
                                     "close": round(float(row["Close"]), 2)})
                vol_data.append({"time": ts,
                                  "value": int(row["Volume"]) if "Volume" in row else 0,
                                  "color": "rgba(38,166,154,0.5)" if row["Close"] >= row["Open"] else "rgba(239,83,80,0.5)"})

            # EMA(20) series
            ema_vals = df["Close"].ewm(span=20, adjust=False).mean()
            ema_data = [{"time": int(idx.timestamp()), "value": round(float(v), 2)}
                        for idx, v in zip(df.index, ema_vals) if hasattr(idx, "timestamp")]

            # VWAP series
            typ = (df["High"] + df["Low"] + df["Close"]) / 3
            cum_v = df["Volume"].cumsum()
            cum_tv = (typ * df["Volume"]).cumsum()
            vwap_vals = cum_tv / cum_v
            vwap_pts = [{"time": int(idx.timestamp()), "value": round(float(v), 2)}
                        for idx, v in zip(df.index, vwap_vals) if hasattr(idx, "timestamp") and not np.isnan(v)]

            # Markers
            markers = []
            for s in all_signals[-3:]:
                sig_ts = int(s["index"].timestamp()) if hasattr(s["index"], "timestamp") else 0
                markers.append({
                    "time": sig_ts,
                    "position": "belowBar" if s["action"] == "BUY" else "aboveBar",
                    "color": "#26a69a" if s["action"] == "BUY" else "#ef5350",
                    "shape": "arrowUp" if s["action"] == "BUY" else "arrowDown",
                    "text": s["action"],
                })

            last_price = round(float(df["Close"].iloc[-1]), 2)
            price_color = "#26a69a" if day_chg >= 0 else "#ef5350"
            chart_mode = st.session_state.chart_type

            candle_json  = json.dumps(candle_data)
            vol_json     = json.dumps(vol_data)
            ema_json     = json.dumps(ema_data)
            vwap_json    = json.dumps(vwap_pts)
            markers_json = json.dumps(markers)

            chart_html = f"""
<div style="background:#131722;border-radius:8px;overflow:hidden;">
<div id="chart_container" style="width:100%;height:520px;"></div>
</div>
<div style="display:flex;gap:16px;padding:6px 10px;background:#0e0e1a;font-size:0.72em;align-items:center;">
  <span><span style="color:#f59e0b;">━</span> EMA(20)</span>
  <span><span style="color:#60a5fa;">┅</span> VWAP</span>
  <span><span style="color:#26a69a;">█</span> Bull candle</span>
  <span><span style="color:#ef5350;">█</span> Bear candle</span>
  <span style="margin-left:auto;color:#6b7280;">
    O {df['Open'].iloc[0]:,.2f} &nbsp; H {df['High'].max():,.2f} &nbsp; L {df['Low'].min():,.2f} &nbsp; C {last_price:,.2f}
  </span>
</div>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<script>
(function() {{
  var container = document.getElementById('chart_container');
  var chart = LightweightCharts.createChart(container, {{
    width: container.clientWidth, height: 520,
    layout: {{ background: {{ type: 'solid', color: '#131722' }}, textColor: '#9ca3af', fontSize: 11 }},
    grid: {{ vertLines: {{ color: 'rgba(42,46,57,0.4)' }}, horzLines: {{ color: 'rgba(42,46,57,0.4)' }} }},
    crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
    rightPriceScale: {{ borderColor: '#2a2e39', scaleMargins: {{ top: 0.05, bottom: 0.22 }} }},
    timeScale: {{ borderColor: '#2a2e39', timeVisible: true, secondsVisible: false, rightOffset: 5 }},
  }});

  var mainSeries;
  var mode = '{chart_mode}';
  if (mode === 'Candles') {{
    mainSeries = chart.addCandlestickSeries({{
      upColor: '#26a69a', downColor: '#ef5350',
      borderUpColor: '#26a69a', borderDownColor: '#ef5350',
      wickUpColor: '#26a69a', wickDownColor: '#ef5350',
    }});
    mainSeries.setData({candle_json});
  }} else if (mode === 'Line') {{
    mainSeries = chart.addLineSeries({{ color: '#387ed1', lineWidth: 2 }});
    var lineData = {candle_json}.map(d => ({{time: d.time, value: d.close}}));
    mainSeries.setData(lineData);
  }} else {{
    mainSeries = chart.addAreaSeries({{
      topColor: 'rgba(56,126,209,0.3)', bottomColor: 'rgba(56,126,209,0.0)',
      lineColor: '#387ed1', lineWidth: 2,
    }});
    var areaData = {candle_json}.map(d => ({{time: d.time, value: d.close}}));
    mainSeries.setData(areaData);
  }}

  // Current price line
  mainSeries.createPriceLine({{ price: {last_price}, color: '{price_color}', lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: '' }});

  // S/R lines
  mainSeries.createPriceLine({{ price: {sr['r2']}, color: '#22c55e', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'R2' }});
  mainSeries.createPriceLine({{ price: {sr['r1']}, color: '#34d399', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'R1' }});
  mainSeries.createPriceLine({{ price: {sr['pivot']}, color: '#a5b4fc', lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: 'Pivot' }});
  mainSeries.createPriceLine({{ price: {sr['s1']}, color: '#f87171', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'S1' }});
  mainSeries.createPriceLine({{ price: {sr['s2']}, color: '#ef4444', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'S2' }});

  // EMA(20) line
  var emaSeries = chart.addLineSeries({{ color: '#f59e0b', lineWidth: 2, lastValueVisible: false, priceLineVisible: false }});
  emaSeries.setData({ema_json});

  // VWAP dotted line
  var vwapSeries = chart.addLineSeries({{ color: '#60a5fa', lineWidth: 1, lineStyle: 1, lastValueVisible: false, priceLineVisible: false }});
  vwapSeries.setData({vwap_json});

  // Volume
  var volSeries = chart.addHistogramSeries({{ priceFormat: {{ type: 'volume' }}, priceScaleId: 'vol' }});
  volSeries.priceScale().applyOptions({{ scaleMargins: {{ top: 0.8, bottom: 0 }} }});
  volSeries.setData({vol_json});

  // Markers
  var markers = {markers_json};
  if (markers.length > 0 && mode === 'Candles') mainSeries.setMarkers(markers);

  chart.timeScale().fitContent();
  new ResizeObserver(() => chart.applyOptions({{ width: container.clientWidth }})).observe(container);
}})();
</script>
"""
            components.html(chart_html, height=580, scrolling=False)


    # ══════════════════════════════════════════
    #  TAB 2: OPTION CHAIN
    # ══════════════════════════════════════════
    with tab_oc:
        nse_sym_oc = active_sym.get("nse", "")

        if not nse_sym_oc:
            st.info("Option chain is only available for NSE instruments (indices and F&O stocks).")
        else:
            with st.spinner("Loading option chain..."):
                oc_raw = _load_option_chain_nse(nse_sym_oc)

            if oc_raw is None or "records" not in oc_raw:
                st.warning(
                    f"Could not fetch option chain for **{nse_sym_oc}** from NSE. "
                    "NSE periodically rate-limits requests — will retry automatically. "
                    "If this persists, try refreshing after a minute."
                )
                if st.button("Retry Now", key="oc_retry"):
                    st.cache_data.clear()
                    st.rerun()
            else:
                records = oc_raw["records"]
                expiry_dates = records.get("expiryDates", [])
                chain_data   = records.get("data", [])
                spot_oc = spot_price if data_ok else 0

                # Expiry + strikes selectors
                exp_col, strikes_col, _ = st.columns([3, 2, 3])
                with exp_col:
                    selected_expiry = st.selectbox("EXPIRY", expiry_dates, index=0,
                                                    key="oc_exp", label_visibility="visible")
                with strikes_col:
                    strikes_range = st.selectbox("STRIKES", ["± 5 (ATM)", "± 10 (ATM)", "± 15 (ATM)", "All"],
                                                  index=1, key="oc_strikes", label_visibility="visible")
                strike_window = {"± 5 (ATM)": 5, "± 10 (ATM)": 10, "± 15 (ATM)": 15, "All": 999}.get(strikes_range, 10)

                # Compute stats
                stats = compute_option_stats(chain_data, selected_expiry, spot_oc)
                pcr_color = "#4caf50" if stats["pcr_label"] == "BULLISH" else ("#ef4444" if stats["pcr_label"] == "BEARISH" else "#9ca3af")

                days_to_expiry = ""
                if selected_expiry:
                    try:
                        exp_dt = datetime.strptime(selected_expiry, "%d-%b-%Y")
                        days   = (exp_dt - datetime.now()).days
                        days_to_expiry = f"{days} days to expiry"
                    except Exception:
                        pass

                # Stats bar
                st.markdown(f"""
                <div style="display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin-bottom:12px;">
                  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:8px 10px;">
                    <div style="color:#6b7280;font-size:0.58em;text-transform:uppercase;letter-spacing:1px;">UNDERLYING</div>
                    <div style="color:#e8e8e8;font-size:1.1em;font-weight:700;">{spot_oc:,.2f}</div>
                    <div style="color:#6b7280;font-size:0.62em;">{nse_sym_oc}</div>
                  </div>
                  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:8px 10px;">
                    <div style="color:#6b7280;font-size:0.58em;text-transform:uppercase;letter-spacing:1px;">PCR (OI)</div>
                    <div style="color:{pcr_color};font-size:1.1em;font-weight:700;">{stats['pcr']}</div>
                    <div style="color:{pcr_color};font-size:0.62em;">{stats['pcr_label']}</div>
                  </div>
                  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:8px 10px;">
                    <div style="color:#6b7280;font-size:0.58em;text-transform:uppercase;letter-spacing:1px;">MAX PAIN</div>
                    <div style="color:#fbbf24;font-size:1.1em;font-weight:700;">{stats['max_pain']:,}</div>
                    <div style="color:#6b7280;font-size:0.62em;">{round(abs(spot_oc - stats['max_pain']) / spot_oc * 100, 2) if spot_oc > 0 else 0:.2f}% from spot</div>
                  </div>
                  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:8px 10px;">
                    <div style="color:#6b7280;font-size:0.58em;text-transform:uppercase;letter-spacing:1px;">TOTAL CALL OI</div>
                    <div style="color:#22c55e;font-size:1.1em;font-weight:700;">{_fmt_oi(stats['total_ce_oi'])}</div>
                    <div style="color:#6b7280;font-size:0.62em;">resistance build-up</div>
                  </div>
                  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:8px 10px;">
                    <div style="color:#6b7280;font-size:0.58em;text-transform:uppercase;letter-spacing:1px;">TOTAL PUT OI</div>
                    <div style="color:#ef4444;font-size:1.1em;font-weight:700;">{_fmt_oi(stats['total_pe_oi'])}</div>
                    <div style="color:#6b7280;font-size:0.62em;">support build-up</div>
                  </div>
                  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:8px 10px;">
                    <div style="color:#6b7280;font-size:0.58em;text-transform:uppercase;letter-spacing:1px;">EXPIRY</div>
                    <div style="color:#e8e8e8;font-size:1.0em;font-weight:700;">{selected_expiry or "--"}</div>
                    <div style="color:#6b7280;font-size:0.62em;">{days_to_expiry}</div>
                  </div>
                </div>
                """, unsafe_allow_html=True)

                # ITM legend
                st.markdown("""
                <div style="display:flex;gap:12px;margin-bottom:8px;font-size:0.72em;">
                  <span><span style="background:rgba(34,197,94,0.15);padding:1px 6px;border-radius:3px;color:#22c55e;">■ ITM Call</span></span>
                  <span><span style="background:rgba(239,68,68,0.15);padding:1px 6px;border-radius:3px;color:#ef4444;">■ ITM Put</span></span>
                  <span><span style="background:rgba(251,191,36,0.15);padding:1px 6px;border-radius:3px;color:#fbbf24;">■ ATM</span></span>
                </div>
                """, unsafe_allow_html=True)

                # Build chain rows
                chain_rows = []
                all_strikes = set()
                for item in chain_data:
                    if item.get("expiryDate") != selected_expiry:
                        continue
                    strike = item.get("strikePrice", 0)
                    all_strikes.add(strike)
                    ce = item.get("CE", {})
                    pe = item.get("PE", {})
                    chain_rows.append({
                        "strike": strike,
                        "ce_oi": ce.get("openInterest", 0),
                        "ce_oi_chg": ce.get("changeinOpenInterest", 0),
                        "ce_vol": ce.get("totalTradedVolume", 0),
                        "ce_iv": ce.get("impliedVolatility", 0),
                        "ce_bid": ce.get("bidprice", 0),
                        "ce_ask": ce.get("askprice", 0),
                        "ce_ltp": ce.get("lastPrice", 0),
                        "pe_ltp": pe.get("lastPrice", 0),
                        "pe_bid": pe.get("bidprice", 0),
                        "pe_ask": pe.get("askprice", 0),
                        "pe_iv": pe.get("impliedVolatility", 0),
                        "pe_vol": pe.get("totalTradedVolume", 0),
                        "pe_oi_chg": pe.get("changeinOpenInterest", 0),
                        "pe_oi": pe.get("openInterest", 0),
                    })

                chain_rows.sort(key=lambda r: r["strike"])
                atm = min(all_strikes, key=lambda s: abs(s - spot_oc)) if all_strikes and spot_oc > 0 else 0

                # Filter to window
                if atm > 0 and strike_window < 999:
                    sorted_s = sorted(all_strikes)
                    ai = sorted_s.index(atm) if atm in sorted_s else len(sorted_s) // 2
                    visible = set(sorted_s[max(0, ai - strike_window): ai + strike_window + 1])
                    chain_rows = [r for r in chain_rows if r["strike"] in visible]

                if chain_rows:
                    tbl = '<table style="width:100%;border-collapse:collapse;font-size:0.78em;text-align:center;">'
                    tbl += '<thead>'
                    tbl += '<tr style="background:#1e293b;">'
                    tbl += '<th colspan="7" style="padding:5px;color:#22c55e;border-bottom:1px solid #2a2a4a;">CALLS</th>'
                    tbl += '<th style="padding:5px;color:#fbbf24;border-bottom:1px solid #2a2a4a;">STRIKE</th>'
                    tbl += '<th colspan="7" style="padding:5px;color:#ef4444;border-bottom:1px solid #2a2a4a;">PUTS</th>'
                    tbl += '</tr>'
                    tbl += '<tr style="background:#12121f;">'
                    for h in ["OI","CHG OI","VOL","IV","BID","ASK","LTP"]:
                        tbl += f'<th style="padding:5px 4px;color:#4b5563;font-weight:500;border-bottom:1px solid #2a2a4a;">{h}</th>'
                    tbl += '<th style="padding:5px;color:#fbbf24;font-weight:700;border-bottom:1px solid #2a2a4a;background:#1a1a2e;">PRICE</th>'
                    for h in ["LTP","BID","ASK","IV","VOL","CHG OI","OI"]:
                        tbl += f'<th style="padding:5px 4px;color:#4b5563;font-weight:500;border-bottom:1px solid #2a2a4a;">{h}</th>'
                    tbl += '</tr></thead><tbody>'

                    for r in chain_rows:
                        is_atm   = r["strike"] == atm
                        is_itm_ce = spot_oc > 0 and r["strike"] < spot_oc
                        is_itm_pe = spot_oc > 0 and r["strike"] > spot_oc
                        row_cls = "atm" if is_atm else ""
                        ce_bg = "background:rgba(34,197,94,0.07);" if is_itm_ce else ""
                        pe_bg = "background:rgba(239,68,68,0.07);" if is_itm_pe else ""
                        atm_bg = "background:rgba(251,191,36,0.12);border-top:1px solid rgba(251,191,36,0.4);border-bottom:1px solid rgba(251,191,36,0.4);" if is_atm else ""

                        def _oi_chg_clr(v): return "#22c55e" if v > 0 else ("#ef4444" if v < 0 else "#6b7280")
                        def _ltp_clr(v): return "#e8e8e8"

                        tbl += f'<tr style="border-bottom:1px solid rgba(42,42,74,0.3);">'
                        tbl += f'<td style="padding:4px;color:#d1d5db;{ce_bg}{atm_bg}">{_fmt_oi(r["ce_oi"])}</td>'
                        tbl += f'<td style="padding:4px;color:{_oi_chg_clr(r["ce_oi_chg"])};{ce_bg}{atm_bg}">{_fmt_oi(r["ce_oi_chg"]) if r["ce_oi_chg"] != 0 else "0"}</td>'
                        tbl += f'<td style="padding:4px;color:#d1d5db;{ce_bg}{atm_bg}">{_fmt_oi(r["ce_vol"])}</td>'
                        tbl += f'<td style="padding:4px;color:#d1d5db;{ce_bg}{atm_bg}">{r["ce_iv"]:.1f}</td>'
                        tbl += f'<td style="padding:4px;color:#d1d5db;{ce_bg}{atm_bg}">{r["ce_bid"]:.2f}</td>'
                        tbl += f'<td style="padding:4px;color:#d1d5db;{ce_bg}{atm_bg}">{r["ce_ask"]:.2f}</td>'
                        tbl += f'<td style="padding:4px;color:#22c55e;font-weight:600;{ce_bg}{atm_bg}">{r["ce_ltp"]:.2f}</td>'
                        tbl += f'<td style="padding:4px;color:#fbbf24;font-weight:700;background:#1a1a2e;{atm_bg}">{int(r["strike"]):,}{" ★" if is_atm else ""}</td>'
                        tbl += f'<td style="padding:4px;color:#ef4444;font-weight:600;{pe_bg}{atm_bg}">{r["pe_ltp"]:.2f}</td>'
                        tbl += f'<td style="padding:4px;color:#d1d5db;{pe_bg}{atm_bg}">{r["pe_bid"]:.2f}</td>'
                        tbl += f'<td style="padding:4px;color:#d1d5db;{pe_bg}{atm_bg}">{r["pe_ask"]:.2f}</td>'
                        tbl += f'<td style="padding:4px;color:#d1d5db;{pe_bg}{atm_bg}">{r["pe_iv"]:.1f}</td>'
                        tbl += f'<td style="padding:4px;color:#d1d5db;{pe_bg}{atm_bg}">{_fmt_oi(r["pe_vol"])}</td>'
                        tbl += f'<td style="padding:4px;color:{_oi_chg_clr(r["pe_oi_chg"])};{pe_bg}{atm_bg}">{_fmt_oi(r["pe_oi_chg"]) if r["pe_oi_chg"] != 0 else "0"}</td>'
                        tbl += f'<td style="padding:4px;color:#d1d5db;{pe_bg}{atm_bg}">{_fmt_oi(r["pe_oi"])}</td>'
                        tbl += '</tr>'

                    tbl += '</tbody></table>'
                    st.markdown(tbl, unsafe_allow_html=True)
                    st.caption(f"Spot: ₹{spot_oc:,.2f}  ·  ATM: {int(atm):,}  ·  Expiry: {selected_expiry}  ·  Source: NSE India")
                else:
                    st.info("No option chain rows for selected expiry.")


    # ══════════════════════════════════════════
    #  TAB 3: AI NEWS
    # ══════════════════════════════════════════
    with tab_news:
        news_col, sent_col = st.columns([7, 3])

        with news_col:
            # Header with filter buttons
            filter_html = '<div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap;">'
            filter_html += '<span style="background:#6366f1;color:white;padding:2px 8px;border-radius:4px;font-size:0.72em;font-weight:700;">AI</span>'
            filter_html += '<span style="color:#e8e8e8;font-size:0.9em;font-weight:600;margin-right:4px;">Intel Feed</span>'
            filter_html += '<span style="background:#ef4444;color:white;padding:1px 6px;border-radius:20px;font-size:0.6em;font-weight:700;">LIVE</span>'
            filter_html += '</div>'
            st.markdown(filter_html, unsafe_allow_html=True)

            # Filter tabs
            filter_choice = st.radio(
                "filter",
                [f"All  {len(news_data)}", "Bullish", "Bearish", "High impact", "auto-refresh · 30s"],
                horizontal=True, key="news_filter_radio", label_visibility="collapsed",
            )

            if news_data:
                for i, article in enumerate(news_data[:8]):
                    headline = article.get("headline", "")
                    url      = article.get("url", "")
                    source   = article.get("source", "")
                    summary  = article.get("summary", headline[:120])

                    analysis  = _news_sentiment(headline)
                    sentiment = article.get("sentiment", analysis["sentiment"]).upper()
                    impact    = analysis["impact"]
                    ai_action_text = _ai_action(headline)

                    # Filter logic
                    if "Bullish" in filter_choice and sentiment != "BULLISH":
                        continue
                    if "Bearish" in filter_choice and sentiment != "BEARISH":
                        continue
                    if "High impact" in filter_choice and "HIGH" not in impact:
                        continue

                    sent_c = "#4caf50" if sentiment == "BULLISH" else ("#ef4444" if sentiment == "BEARISH" else "#9ca3af")
                    sent_bg = "#0d2318" if sentiment == "BULLISH" else ("#2a0a0a" if sentiment == "BEARISH" else "#1a1a2e")
                    imp_c   = "#ef4444" if "HIGH" in impact else ("#f59e0b" if "MEDIUM" in impact else "#6b7280")
                    link_part = f'<a href="{url}" target="_blank" style="color:#60a5fa;font-size:0.7em;text-decoration:none;">Read →</a>' if url else ""

                    card_html = f"""
<div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:12px 14px;margin:6px 0;border-left:3px solid {sent_c};">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap;">
    <span style="background:{sent_bg};color:{sent_c};padding:2px 8px;border-radius:4px;font-size:0.65em;font-weight:700;">{sentiment}</span>
    <span style="color:{imp_c};font-size:0.65em;font-weight:600;">{impact}</span>
    <span style="color:#4b5563;font-size:0.62em;margin-left:auto;">N-{9400+i}</span>
  </div>
  <div style="color:#e8e8e8;font-size:0.88em;font-weight:600;line-height:1.4;margin-bottom:4px;">{headline}</div>
  <div style="color:#9ca3af;font-size:0.78em;line-height:1.5;margin-bottom:6px;">{summary}</div>
  <div style="background:#1a1a2e;border-left:2px solid #387ed1;padding:6px 10px;margin:6px 0;border-radius:0 4px 4px 0;">
    <div style="color:#387ed1;font-size:0.6em;font-weight:700;text-transform:uppercase;letter-spacing:1px;">AI ACTION</div>
    <div style="color:#d1d5db;font-size:0.78em;margin-top:2px;">{ai_action_text}</div>
  </div>
  <div style="display:flex;justify-content:space-between;align-items:center;margin-top:4px;">
    <span style="color:#4b5563;font-size:0.65em;">{source}</span>
    {link_part}
  </div>
</div>"""
                    st.markdown(card_html, unsafe_allow_html=True)
            else:
                st.info("News loading... will auto-refresh every 5 minutes.")

        with sent_col:
            # Market Sentiment Gauge
            sent_score = 50
            if data_ok and rsi_d and st_d and vwap_d:
                pcr_val = oi_d.get("pcr", 0.8) if oi_d else 0.8
                sent_score = _market_sentiment_score(rsi_d["value"], pcr_val, st_d["direction"], vwap_d["signal"])

            sent_label = "RISK-ON" if sent_score >= 60 else ("RISK-OFF" if sent_score <= 40 else "NEUTRAL")
            sent_clr   = "#4caf50" if sent_score >= 60 else ("#ef4444" if sent_score <= 40 else "#f59e0b")
            gauge_pct  = sent_score

            st.markdown(f"""
<div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:12px;margin-bottom:10px;">
  <div style="color:#6b7280;font-size:0.62em;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;">MARKET SENTIMENT</div>
  <div style="font-size:2.2em;font-weight:700;color:#e8e8e8;">{sent_score}<span style="font-size:0.4em;color:#6b7280;"> / 100</span></div>
  <div style="background:linear-gradient(to right, #ef4444 0%, #fbbf24 50%, #4caf50 100%);height:6px;border-radius:3px;margin:8px 0;position:relative;">
    <div style="position:absolute;left:{gauge_pct}%;top:-3px;width:4px;height:12px;background:white;border-radius:2px;transform:translateX(-50%);"></div>
  </div>
  <div style="display:flex;justify-content:space-between;margin-bottom:8px;">
    <span style="font-size:0.6em;color:#ef4444;">Bearish</span>
    <span style="font-size:0.6em;color:#4caf50;">Bullish</span>
  </div>
  <div style="color:{sent_clr};font-size:0.72em;font-weight:700;background:{sent_clr}22;padding:2px 8px;border-radius:4px;display:inline-block;">{sent_label}</div>
  {"<br><br>" + '<span style="color:#4b5563;font-size:0.62em;">● ' + str(sum(1 for s in all_signals if s["action"]=="BUY")) + ' bull &nbsp; ● ' + str(sum(1 for s in all_signals if s["action"]=="SELL")) + ' bear signal(s) detected</span>' if data_ok else ""}
</div>
""", unsafe_allow_html=True)

            # Active Signals (open trades)
            st.markdown('<div style="color:#6b7280;font-size:0.62em;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;">ACTIVE SIGNALS</div>', unsafe_allow_html=True)
            open_trades = get_open_trades()
            if open_trades:
                for t in open_trades[:4]:
                    pnl_approx = 0
                    sig_color = "#4caf50" if t.get("option_type") == "CE" else "#ef4444"
                    sig_label = "BULLISH" if t.get("option_type") == "CE" else "BEARISH"
                    strength = "STRONG"
                    contract = f"{t.get('instrument','')} {t.get('strike','')} {t.get('option_type','')}"
                    entry = t.get("entry_price", 0)
                    target = t.get("target_price", 0)
                    sl = t.get("stop_loss", 0)
                    st.markdown(f"""
<div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:10px;margin:4px 0;border-left:3px solid {sig_color};">
  <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
    <span style="color:{sig_color};font-size:0.68em;font-weight:700;">{sig_label}</span>
    <span style="color:#6b7280;font-size:0.62em;">{strength}</span>
  </div>
  <div style="color:#e8e8e8;font-size:0.82em;font-weight:600;">{contract}</div>
  <div style="display:flex;gap:12px;margin-top:4px;font-size:0.68em;color:#6b7280;">
    <span>ENTRY <span style="color:#e8e8e8;">{entry}</span></span>
    <span>SL <span style="color:#ef4444;">{sl}</span></span>
    <span>T1 <span style="color:#4caf50;">{target}</span></span>
  </div>
</div>""", unsafe_allow_html=True)
            else:
                st.markdown('<div style="color:#4b5563;font-size:0.78em;padding:8px 0;">No active signals. Auto-fires on next BUY/SELL.</div>', unsafe_allow_html=True)

            # Claude AI Analysis
            if data_ok and rsi_d:
                st.markdown('<div style="color:#6b7280;font-size:0.62em;text-transform:uppercase;letter-spacing:1px;margin:10px 0 4px 0;">CLAUDE ANALYSIS</div>', unsafe_allow_html=True)
                prices_dict = {
                    "nifty": spot_price if active_sym.get("nse") == "NIFTY" else None,
                    "banknifty": spot_price if active_sym.get("nse") == "BANKNIFTY" else None,
                }
                with st.spinner("AI analyzing..."):
                    try:
                        analysis_text = analyze_market(
                            prices_dict, signal, rsi_d, macd_d, st_d, vwap_d, oi_d, news_data,
                        )
                    except Exception:
                        analysis_text = "Analysis unavailable — check Anthropic API key in secrets."
                st.markdown(
                    f'<div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:12px;">'
                    f'<p style="color:#d1d5db;font-size:0.82em;line-height:1.7;margin:0;">{analysis_text}</p>'
                    f'</div>',
                    unsafe_allow_html=True,
                )


    # ══════════════════════════════════════════
    #  TAB 4: SMS ADMIN
    # ══════════════════════════════════════════
    with tab_sms:
        # ══════════════════════════════════════════
        #  ZERODHA KITE CONNECT — auth & status
        # ══════════════════════════════════════════

        if st.session_state.get("kite_just_connected"):
            st.session_state.pop("kite_just_connected", None)

        # ── Zerodha status card ──
        if kite_live:
            # Connected — show account info + positions
            try:
                profile = zerodha_api.get_profile()
                margins = zerodha_api.get_margins()
                equity  = margins.get("equity", {}).get("available", {})
                cash    = equity.get("cash", 0) or equity.get("live_balance", 0)
                user_name = profile.get("user_name", "--")
                user_id   = profile.get("user_id", "--")
            except Exception:
                user_name, user_id, cash = "--", "--", 0

            st.markdown(f"""
<div style="background:#0d1f0d;border:1px solid #1a3a1a;border-radius:8px;padding:12px 14px;margin-bottom:12px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
    <span style="color:#4caf50;font-weight:700;font-size:0.9em;">&#9889; ZERODHA CONNECTED — REAL-TIME DATA LIVE</span>
    <span style="color:#4b5563;font-size:0.7em;">Kite Connect v3</span>
  </div>
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;">
    <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:8px 10px;">
      <div style="color:#6b7280;font-size:0.58em;text-transform:uppercase;letter-spacing:1px;">ACCOUNT</div>
      <div style="color:#e8e8e8;font-weight:600;font-size:0.88em;">{user_name}</div>
      <div style="color:#4b5563;font-size:0.68em;">{user_id}</div>
    </div>
    <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:8px 10px;">
      <div style="color:#6b7280;font-size:0.58em;text-transform:uppercase;letter-spacing:1px;">AVAILABLE MARGIN</div>
      <div style="color:#4caf50;font-weight:700;font-size:1.05em;">&#8377;{cash:,.0f}</div>
    </div>
    <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:8px 10px;">
      <div style="color:#6b7280;font-size:0.58em;text-transform:uppercase;letter-spacing:1px;">DATA FEED</div>
      <div style="color:#7c3aed;font-weight:700;font-size:0.88em;">&#9889; REAL-TIME</div>
      <div style="color:#4b5563;font-size:0.68em;">0ms delay</div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

            pos_col, ord_col = st.columns(2)
            with pos_col:
                st.markdown('<div style="color:#9ca3af;font-size:0.78em;font-weight:600;margin-bottom:6px;text-transform:uppercase;letter-spacing:0.5px;">Positions Today</div>', unsafe_allow_html=True)
                try:
                    positions = zerodha_api.get_positions().get("day", [])
                    if positions:
                        for p in positions[:6]:
                            pnl = p.get("pnl", 0)
                            clr = "#4caf50" if pnl >= 0 else "#ef4444"
                            st.markdown(
                                f'<div style="background:#12121f;border:1px solid #2a2a4a;border-radius:4px;'
                                f'padding:6px 10px;margin-bottom:4px;font-size:0.78em;display:flex;justify-content:space-between;">'
                                f'<span style="color:#e8e8e8;font-weight:600;">{p.get("tradingsymbol","")}</span>'
                                f'<span style="color:#6b7280;">Qty {p.get("quantity",0)}</span>'
                                f'<span style="color:{clr};font-weight:600;">{pnl:+,.0f}</span></div>',
                                unsafe_allow_html=True
                            )
                    else:
                        st.markdown('<div style="color:#4b5563;font-size:0.78em;padding:8px 0;">No positions today</div>', unsafe_allow_html=True)
                except Exception:
                    st.markdown('<div style="color:#4b5563;font-size:0.75em;">--</div>', unsafe_allow_html=True)

            with ord_col:
                st.markdown('<div style="color:#9ca3af;font-size:0.78em;font-weight:600;margin-bottom:6px;text-transform:uppercase;letter-spacing:0.5px;">Orders Today</div>', unsafe_allow_html=True)
                try:
                    orders = zerodha_api.get_orders()
                    if orders:
                        for o in orders[-6:]:
                            status = o.get("status", "")
                            s_clr = "#4caf50" if status == "COMPLETE" else ("#ef4444" if status == "REJECTED" else "#f59e0b")
                            st.markdown(
                                f'<div style="background:#12121f;border:1px solid #2a2a4a;border-radius:4px;'
                                f'padding:6px 10px;margin-bottom:4px;font-size:0.78em;display:flex;justify-content:space-between;">'
                                f'<span style="color:#e8e8e8;">{o.get("tradingsymbol","")}</span>'
                                f'<span style="color:#6b7280;">{o.get("transaction_type","")} {o.get("quantity",0)}</span>'
                                f'<span style="color:{s_clr};">{status}</span></div>',
                                unsafe_allow_html=True
                            )
                    else:
                        st.markdown('<div style="color:#4b5563;font-size:0.78em;padding:8px 0;">No orders today</div>', unsafe_allow_html=True)
                except Exception:
                    st.markdown('<div style="color:#4b5563;font-size:0.75em;">--</div>', unsafe_allow_html=True)

            if st.button("Disconnect Zerodha", key="kite_disconnect", type="secondary"):
                zerodha_api._save_token("", "")
                st.session_state.kite_restore_attempted = False
                st.rerun()

        elif kite_configured:
            # Keys set but not logged in today
            login_url = zerodha_api.get_login_url()
            st.markdown(f"""
<div style="background:#12121f;border:1px solid #2a2a4a;border-radius:8px;padding:16px;margin-bottom:12px;text-align:center;">
  <div style="color:#e8e8e8;font-weight:700;font-size:0.95em;margin-bottom:6px;">Zerodha API Keys Detected</div>
  <div style="color:#6b7280;font-size:0.82em;margin-bottom:16px;">
    Log in once daily to activate real-time data. Token expires at midnight IST.
  </div>
  <a href="{login_url}" target="_blank"
     style="background:#7c3aed;color:white;padding:10px 28px;border-radius:6px;
            font-weight:700;font-size:0.9em;text-decoration:none;display:inline-block;letter-spacing:0.3px;">
    Connect Zerodha &rarr;
  </a>
  <div style="color:#4b5563;font-size:0.7em;margin-top:10px;">
    After login, Zerodha redirects back here automatically with your token.
  </div>
</div>
""", unsafe_allow_html=True)

        else:
            # Keys not set — show minimal note
            st.markdown("""
<div style="background:#1a1a2e;border:1px solid #2a2a4a;border-radius:8px;padding:12px 14px;margin-bottom:12px;">
  <div style="color:#6b7280;font-size:0.8em;">
    <span style="color:#f59e0b;font-weight:600;">Zerodha not configured.</span>
    Add <code>KITE_API_KEY</code> and <code>KITE_API_SECRET</code> to Railway environment variables to enable real-time data.
  </div>
</div>
""", unsafe_allow_html=True)

        st.markdown('<div style="border-bottom:1px solid #2a2a4a;margin-bottom:14px;"></div>', unsafe_allow_html=True)

        subs_list = get_subscribers()
        sms_log   = get_sms_log()
        open_trades_count = len(get_open_trades())

        # ── Stats row ──
        signals_today = len([e for e in sms_log if e.get("timestamp", "")[:10] == now_ist.strftime("%Y-%m-%d")])
        delivered_today = len([e for e in sms_log if e.get("timestamp", "")[:10] == now_ist.strftime("%Y-%m-%d") and e.get("status") == "sent"])
        delivery_rate = round(delivered_today / signals_today * 100) if signals_today else 0

        # Approximate credits from log
        credits_used = len(sms_log)
        credits_left = max(0, 10000 - credits_used)

        st.markdown(f"""
<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:14px;">
  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:10px 12px;">
    <div style="color:#6b7280;font-size:0.58em;text-transform:uppercase;letter-spacing:1px;">ACTIVE SUBSCRIBERS</div>
    <div style="color:#e8e8e8;font-size:1.8em;font-weight:700;">{len(subs_list)}</div>
    <div style="color:#4caf50;font-size:0.65em;">+{max(0,len(subs_list))} this week</div>
  </div>
  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:10px 12px;">
    <div style="color:#6b7280;font-size:0.58em;text-transform:uppercase;letter-spacing:1px;">SIGNALS SENT TODAY</div>
    <div style="color:#e8e8e8;font-size:1.8em;font-weight:700;">{signals_today}</div>
    <div style="color:#6b7280;font-size:0.65em;">{delivery_rate}% delivered</div>
  </div>
  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:10px 12px;">
    <div style="color:#6b7280;font-size:0.58em;text-transform:uppercase;letter-spacing:1px;">SMS CREDITS LEFT</div>
    <div style="color:#e8e8e8;font-size:1.8em;font-weight:700;">{credits_left:,}</div>
    <div style="color:#6b7280;font-size:0.65em;">auto-refill at 1,000</div>
  </div>
  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:10px 12px;">
    <div style="color:#6b7280;font-size:0.58em;text-transform:uppercase;letter-spacing:1px;">AVG OPEN RATE</div>
    <div style="color:#e8e8e8;font-size:1.8em;font-weight:700;">{delivery_rate}%</div>
    <div style="color:#6b7280;font-size:0.65em;">last 7 days</div>
  </div>
</div>
""", unsafe_allow_html=True)

        sms_left_col, sms_right_col = st.columns([3, 2])

        with sms_left_col:
            # Subscriber management header
            st.markdown("""
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
  <span style="color:#e8e8e8;font-size:0.9em;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">SUBSCRIBERS</span>
</div>
""", unsafe_allow_html=True)

            # Filter tabs
            sub_filter = st.radio("sub_f", ["All", "Active", "Inactive"], horizontal=True,
                                   key="sub_filter", label_visibility="collapsed")
            search_sub = st.text_input("Search subscribers", placeholder="Search by phone or name...",
                                        key="search_sub", label_visibility="collapsed")

            add_col1, add_col2, add_col3 = st.columns([3, 2, 1])
            with add_col1:
                new_phone = st.text_input("Phone", placeholder="+91XXXXXXXXXX", key="new_phone", label_visibility="collapsed")
            with add_col2:
                new_name = st.text_input("Name", placeholder="Subscriber name", key="new_name", label_visibility="collapsed")
            with add_col3:
                if st.button("+ Add", key="add_sub_btn", use_container_width=True, type="primary"):
                    if new_phone.strip():
                        if add_subscriber(new_phone.strip(), new_name.strip()):
                            st.success("Added!")
                            st.rerun()
                        else:
                            st.warning("Already exists or invalid number.")
                    else:
                        st.error("Enter a phone number.")

            # Subscriber table
            if subs_list:
                all_subs = subs_list
                if search_sub:
                    all_subs = [s for s in all_subs if search_sub.lower() in s.get("phone","").lower() or search_sub.lower() in s.get("name","").lower()]

                tbl_h = '<table style="width:100%;border-collapse:collapse;font-size:0.78em;">'
                tbl_h += '<thead><tr style="background:#12121f;">'
                for h in ["NAME", "PHONE", "PLAN", "JOINED", "SIGNALS", "STATUS", ""]:
                    tbl_h += f'<th style="padding:7px 8px;color:#4b5563;text-align:left;border-bottom:1px solid #2a2a4a;font-weight:500;">{h}</th>'
                tbl_h += '</tr></thead><tbody>'

                for s in all_subs[:20]:
                    is_active = s.get("active", True)
                    if sub_filter == "Active" and not is_active:
                        continue
                    if sub_filter == "Inactive" and is_active:
                        continue
                    sc = "#4caf50" if is_active else "#ef4444"
                    sl = "ACTIVE" if is_active else "PAUSED"
                    plan = s.get("plan", "BASIC").upper()
                    plan_bg = "#6366f1" if plan == "PRO" else "#374151"
                    joined = (s.get("added", s.get("joined", ""))[:10])
                    signals_rx = s.get("signals_received", s.get("sms_count", "--"))
                    # Mask phone
                    phone = s.get("phone", "")
                    masked = f"+91 {phone[:2]}{'•'*4} {'•'*2}{phone[-3:]}" if len(phone) == 10 else phone
                    tbl_h += f'<tr style="border-bottom:1px solid rgba(42,42,74,0.4);">'
                    tbl_h += f'<td style="padding:7px 8px;color:#e8e8e8;">{s.get("name","-") or "-"}</td>'
                    tbl_h += f'<td style="padding:7px 8px;color:#9ca3af;">{masked}</td>'
                    tbl_h += f'<td style="padding:7px 8px;"><span style="background:{plan_bg};color:white;padding:1px 6px;border-radius:3px;font-size:0.8em;">{plan}</span></td>'
                    tbl_h += f'<td style="padding:7px 8px;color:#6b7280;">{joined}</td>'
                    tbl_h += f'<td style="padding:7px 8px;color:#d1d5db;">{signals_rx}</td>'
                    tbl_h += f'<td style="padding:7px 8px;"><span style="color:{sc};font-size:0.75em;font-weight:600;">● {sl}</span></td>'
                    tbl_h += f'<td style="padding:7px 4px;"></td>'
                    tbl_h += '</tr>'
                tbl_h += '</tbody></table>'
                st.markdown(tbl_h, unsafe_allow_html=True)

                # Remove subscriber
                rem_col1, rem_col2 = st.columns([3, 1])
                with rem_col1:
                    rem_phone = st.text_input("Remove phone", placeholder="Phone to remove", key="rem_phone", label_visibility="collapsed")
                with rem_col2:
                    if st.button("Remove", key="rem_sub_btn", use_container_width=True):
                        if rem_phone.strip():
                            if remove_subscriber(rem_phone.strip()):
                                st.success(f"Removed.")
                                st.rerun()
                            else:
                                st.warning("Not found.")
            else:
                st.info("No subscribers yet. Add numbers above to receive auto SMS alerts.")

            # Delivery Log
            st.markdown('<div style="color:#6b7280;font-size:0.62em;text-transform:uppercase;letter-spacing:1px;margin:12px 0 6px 0;">DELIVERY LOG · TODAY &nbsp; <span style="color:#4b5563;">last 4 broadcasts</span></div>', unsafe_allow_html=True)

            if sms_log:
                log_tbl = '<table style="width:100%;border-collapse:collapse;font-size:0.76em;">'
                log_tbl += '<thead><tr style="background:#12121f;"><th style="padding:6px 8px;color:#4b5563;text-align:left;border-bottom:1px solid #2a2a4a;">TIME</th><th style="padding:6px 8px;color:#4b5563;text-align:left;border-bottom:1px solid #2a2a4a;">SIGNAL</th><th style="padding:6px 8px;color:#4b5563;text-align:center;border-bottom:1px solid #2a2a4a;">SENT</th><th style="padding:6px 8px;color:#4b5563;text-align:center;border-bottom:1px solid #2a2a4a;">STATUS</th></tr></thead><tbody>'

                # Group by broadcast (timestamp prefix)
                seen_ts = set()
                count = 0
                for entry in reversed(sms_log[-50:]):
                    ts_short = entry.get("timestamp", "")[:16]
                    if ts_short in seen_ts:
                        continue
                    seen_ts.add(ts_short)
                    count += 1
                    if count > 8:
                        break
                    sc = "#4caf50" if entry.get("status") == "sent" else "#ef4444"
                    msg_preview = entry.get("message", "")[:30] + "..."
                    log_tbl += f'<tr style="border-bottom:1px solid rgba(42,42,74,0.3);"><td style="padding:6px 8px;color:#6b7280;">{ts_short[11:]}</td><td style="padding:6px 8px;color:#d1d5db;">{msg_preview}</td><td style="padding:6px 8px;text-align:center;color:#9ca3af;">{len([e for e in sms_log if e.get("timestamp","")[:16]==ts_short])}</td><td style="padding:6px 8px;text-align:center;color:{sc};font-weight:600;">{entry.get("status","--")}</td></tr>'
                log_tbl += '</tbody></table>'
                st.markdown(log_tbl, unsafe_allow_html=True)
            else:
                st.info("No SMS sent yet. Signals fire automatically on BUY/SELL detection.")

        with sms_right_col:
            # Broadcast Composer
            st.markdown("""
<div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:14px;">
  <div style="color:#e8e8e8;font-size:0.9em;font-weight:600;margin-bottom:4px;">BROADCAST COMPOSER</div>
  <div style="color:#6b7280;font-size:0.68em;margin-bottom:12px;">Manual signal send. Auto-broadcasts trigger from the Signals engine.</div>
""", unsafe_allow_html=True)

            # Audience
            st.markdown('<div style="color:#6b7280;font-size:0.62em;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">AUDIENCE</div>', unsafe_allow_html=True)
            audience = st.selectbox("audience", ["All subscribers", "Active only", "PRO plan only"],
                                     key="bc_audience", label_visibility="collapsed")

            # Template buttons
            st.markdown('<div style="color:#6b7280;font-size:0.62em;text-transform:uppercase;letter-spacing:1px;margin:8px 0 4px 0;">TEMPLATE</div>', unsafe_allow_html=True)
            tmpl_cols = st.columns(4)
            templates = {
                "Entry signal": f"🔔 SIGNAL | {'BULLISH' if action=='BUY' else 'BEARISH'}\n{active_sym_key} {_atm_strike(spot_price if data_ok else 0)} {'CE' if action=='BUY' else 'PE'}\nEntry: {spot_price if data_ok else '--'}\nSL: {signal.get('stop_loss') or '--'}\nT1: {signal.get('target') or '--'}\nConf: {'BUY' if action=='BUY' else 'SELL'} signal · {st.session_state.chart_tf} TF\nReply STOP to unsubscribe",
                "Target hit":   f"✅ TARGET HIT\n{active_sym_key} position closed\nBooked profit. Well done!\nReply STOP to unsubscribe",
                "Stop loss":    f"⛔ STOP LOSS\n{active_sym_key} SL triggered\nExit position immediately.\nReply STOP to unsubscribe",
                "Market alert": f"⚡ MARKET ALERT\n{active_sym_key} unusual activity\nMonitor closely.\nReply STOP to unsubscribe",
            }

            selected_template = st.session_state.get("selected_template", "Entry signal")
            for i, (label, _) in enumerate(templates.items()):
                with tmpl_cols[i]:
                    is_sel = selected_template == label
                    if st.button(label, key=f"tmpl_{label}",
                                  use_container_width=True,
                                  type="primary" if is_sel else "secondary"):
                        st.session_state["selected_template"] = label
                        st.rerun()

            # Custom message area
            st.markdown('<div style="color:#6b7280;font-size:0.62em;text-transform:uppercase;letter-spacing:1px;margin:8px 0 4px 0;">MESSAGE</div>', unsafe_allow_html=True)
            default_msg = templates.get(selected_template, "")
            bc_message = st.text_area("Message", value=default_msg, height=130, key="bc_message",
                                       label_visibility="collapsed")
            char_count = len(bc_message)
            st.markdown(f'<div style="text-align:right;color:#4b5563;font-size:0.65em;">{char_count}/160 · {"1" if char_count <= 160 else "2"} SMS</div>', unsafe_allow_html=True)

            # Cost estimate
            cost_per_sms = 0.15
            total_cost = round(len(subs_list) * cost_per_sms, 2)
            st.markdown(f"""
<div style="border-top:1px solid #2a2a4a;margin:8px 0;padding-top:8px;">
  <div style="display:flex;justify-content:space-between;font-size:0.7em;color:#6b7280;margin-bottom:3px;">
    <span>Estimated cost</span><span style="color:#e8e8e8;">₹{total_cost}</span>
  </div>
  <div style="display:flex;justify-content:space-between;font-size:0.7em;color:#6b7280;margin-bottom:3px;">
    <span>SMS credits used</span><span style="color:#e8e8e8;">{len(subs_list)} of {credits_left:,}</span>
  </div>
  <div style="display:flex;justify-content:space-between;font-size:0.7em;color:#6b7280;">
    <span>Send window (DLT)</span><span style="color:#4caf50;">OPEN · 09:00–21:00 IST</span>
  </div>
</div>
""", unsafe_allow_html=True)

            bc_btn_cols = st.columns([3, 1])
            with bc_btn_cols[0]:
                if st.button("Send broadcast", key="bc_send", use_container_width=True, type="primary"):
                    if not subs_list:
                        st.warning("No subscribers.")
                    elif not bc_message.strip():
                        st.error("Message is empty.")
                    else:
                        spot_val = spot_price if data_ok else 23000
                        test_trade = {
                            "instrument": active_sym_key,
                            "strike": str(_atm_strike(spot_val)),
                            "option_type": "CE" if action == "BUY" else "PE",
                            "expiry": "Weekly",
                            "entry_price": spot_val,
                            "target_price": signal.get("target") or round(spot_val * 1.01, 2),
                            "stop_loss": signal.get("stop_loss") or round(spot_val * 0.997, 2),
                            "quantity": 1,
                        }
                        results = send_sms_to_all(test_trade, action="BUY")
                        sent = sum(1 for r in results if r.get("status") == "sent")
                        fail = sum(1 for r in results if r.get("status") == "failed")
                        if sent > 0:
                            st.success(f"✓ Broadcast sent to {sent} subscriber(s)")
                        elif fail > 0:
                            err = (results[0].get("api_response") or results[0].get("error") or "unknown")[:80]
                            st.error(f"Failed ({fail}): {err}")
                        else:
                            st.info("No active subscribers.")
            with bc_btn_cols[1]:
                if st.button("Schedule", key="bc_schedule"):
                    st.info("Scheduling coming soon.")

            st.markdown('</div>', unsafe_allow_html=True)
            st.markdown(
                '<div style="color:#4b5563;font-size:0.62em;margin-top:6px;line-height:1.4;">'
                'Auto-appends DLT header <code>NSETRD</code> and unsubscribe footer. '
                'Educational use only — not buy/sell recommendations.</div>',
                unsafe_allow_html=True,
            )

    # ── Footer ──
    st.markdown(
        '<div style="border-top:1px solid #2a2a4a;margin-top:16px;padding:8px 4px;color:#4b5563;font-size:0.68em;">'
        'For educational purposes only. Not financial advice. Always use stop loss. '
        f'App auto-refreshes every {"15s" if mkt_open else "5min"} during market hours.'
        '</div>',
        unsafe_allow_html=True,
    )
