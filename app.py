import streamlit as st
from streamlit_autorefresh import st_autorefresh
from datetime import datetime
import pytz
import concurrent.futures
import pandas as pd
import os

import zerodha_api

from config import (
    SYMBOLS, STOP_LOSS_PCT, TARGET_PCT,
    RSI_PERIOD, RSI_OVERBOUGHT, RSI_OVERSOLD,
    EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER,
)
from data_fetcher import (
    get_spot_price, get_intraday_data, get_option_chain_data,
    get_option_recommendation, is_market_open, get_current_option_ltp,
    get_nse_indices, get_chart_data, get_sparkline_data,
    get_option_chain_nse_direct, compute_option_stats, get_market_opens_in,
    _fmt_oi,
)
from indicators import (
    compute_rsi, compute_macd, compute_supertrend, compute_vwap,
    evaluate_oi, generate_signal, compute_all_signals,
)
from news_scraper import scrape_moneycontrol_news
from claude_analyzer import analyze_market
from notifier import send_signal_email
from trades import create_trade, close_trade, get_open_trades, get_closed_trades, delete_trade
from sms_sender import (
    send_sms_to_all, get_subscribers, add_subscriber,
    remove_subscriber, get_sms_log,
    get_watchlist, add_to_watchlist, remove_from_watchlist,
)
from dhan_api import get_option_chain_for_symbol, get_spot_price_dhan, resolve_symbol

IST = pytz.timezone("Asia/Kolkata")
_TV_INT = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "1h": "60", "1D": "D"}

SYMBOL_ALIASES = {
    "NIFTY": "NIFTY 50", "NIFTY50": "NIFTY 50",
    "BANKNIFTY": "BANK NIFTY", "INFY": "INFOSYS",
    "HDFCBANK": "HDFC BANK", "ICICIBANK": "ICICI BANK",
    "MM": "M&M", "BAJAJAUTO": "BAJAJ-AUTO",
}

SYMBOL_SHORT = {
    "NIFTY 50":   ("NIFTY50",   "Nifty 50 Index"),
    "BANK NIFTY": ("BANKNIFTY", "Nifty Bank Index"),
    "RELIANCE":   ("RELIANCE",  "Reliance Industries"),
    "HDFC BANK":  ("HDFCBANK",  "HDFC Bank"),
    "TCS":        ("TCS",       "Tata Consultancy"),
    "INFOSYS":    ("INFY",      "Infosys"),
    "IDEA":       ("IDEA",      "Vodafone Idea"),
    "SBIN":       ("SBIN",      "State Bank of India"),
    "ICICI BANK": ("ICICIBANK", "ICICI Bank"),
    "ITC":        ("ITC",       "ITC Limited"),
    "ZOMATO":     ("ZOMATO",    "Zomato"),
    "TATAMOTORS": ("TATAMOTORS","Tata Motors"),
}

st.set_page_config(
    page_title="Options Terminal",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Token restore — no NFO pre-warm
if "kite_restore_attempted" not in st.session_state:
    st.session_state.kite_restore_attempted = True
    zerodha_api.restore_saved_token()

# OAuth redirect handler
_qp = st.query_params
if _qp.get("action") == "login" and _qp.get("request_token"):
    if zerodha_api.complete_login(_qp["request_token"]):
        st.session_state["kite_just_connected"] = True
    st.query_params.clear()
    st.rerun()

kite_configured = bool(os.environ.get("KITE_API_KEY","").strip() and os.environ.get("KITE_API_SECRET","").strip())
kite_live = zerodha_api.is_connected() if kite_configured else False

_refresh_ms = 15_000 if is_market_open() else 300_000
st_autorefresh(interval=_refresh_ms, limit=0, key="live_refresh")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
* { font-family: 'Inter', sans-serif !important; box-sizing: border-box; }
.block-container { padding: 0 !important; max-width: 100% !important; }
section[data-testid="stMain"] > div { padding: 0 !important; }
html, body, [data-testid="stAppViewContainer"] { background: #0e0e1a !important; }
#MainMenu, footer, .stDeployButton, [data-testid="manage-app-button"] { display: none !important; }
header[data-testid="stHeader"] { background: transparent !important; height: 0 !important; min-height: 0 !important; visibility: hidden !important; }
div[data-testid="stSidebar"], button[data-testid="stSidebarCollapsedControl"], [data-testid="stDecoration"] { display: none !important; }
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: #0e0e1a; }
::-webkit-scrollbar-thumb { background: #2a2a4a; border-radius: 3px; }
button[data-baseweb="tab"] { background: transparent !important; border: none !important; border-bottom: 2px solid transparent !important; color: #6b7280 !important; font-size: 0.88em !important; padding: 8px 16px !important; }
button[data-baseweb="tab"][aria-selected="true"] { border-bottom: 2px solid #387ed1 !important; color: #e8e8e8 !important; font-weight: 600 !important; }
div[data-testid="stTabsTabList"] { border-bottom: 1px solid #2a2a4a !important; }
[data-testid="stTabsContent"] { padding: 10px 4px !important; }
div[data-testid="stRadio"] > div { flex-direction: row !important; gap: 1px !important; background: #12121f; border: 1px solid #2a2a4a; border-radius: 6px; padding: 3px; display: inline-flex !important; }
div[data-testid="stRadio"] > div > label { background: transparent !important; border: none !important; border-radius: 4px !important; color: #6b7280 !important; cursor: pointer !important; font-size: 0.76em !important; padding: 4px 9px !important; white-space: nowrap !important; margin: 0 !important; }
div[data-testid="stRadio"] > div > label:has(input:checked) { background: #1e293b !important; color: #e8e8e8 !important; font-weight: 600 !important; }
div[data-testid="stRadio"] > div > label > div:first-child { display: none !important; }
div[data-testid="stRadio"] label p { margin: 0 !important; }
[data-testid="stTextInput"] input { background: #12121f !important; border: 1px solid #2a2a4a !important; border-radius: 6px !important; color: #e8e8e8 !important; font-size: 0.82em !important; padding: 5px 9px !important; }
[data-testid="stSelectbox"] div[data-baseweb="select"] > div:first-child { background: #12121f !important; border: 1px solid #2a2a4a !important; border-radius: 6px !important; color: #e8e8e8 !important; font-size: 0.82em !important; min-height: 32px !important; }
button[kind="primary"] { background: #387ed1 !important; border: none !important; border-radius: 6px !important; color: white !important; font-weight: 600 !important; }
button[kind="secondary"] { background: #12121f !important; border: 1px solid #2a2a4a !important; border-radius: 6px !important; color: #d1d5db !important; }
div[data-testid="column"]:first-child [data-testid="stButton"] button { background: transparent !important; border: none !important; border-bottom: 1px solid rgba(42,42,74,0.4) !important; border-radius: 0 !important; color: #e2e8f0 !important; font-size: 0.82em !important; font-weight: 600 !important; padding: 6px 8px 4px !important; text-align: left !important; width: 100% !important; box-shadow: none !important; }
div[data-testid="column"]:first-child [data-testid="stButton"] button:hover { background: rgba(56,126,209,0.07) !important; }
.stCaption p { color: #4b5563 !important; font-size: 0.72em !important; }
[data-testid="stAlert"] { background: #1a1a2e !important; border: 1px solid #2a2a4a !important; border-radius: 6px !important; color: #9ca3af !important; font-size: 0.82em !important; }
textarea { background: #12121f !important; border: 1px solid #2a2a4a !important; border-radius: 6px !important; color: #e8e8e8 !important; font-size: 0.82em !important; }
</style>
""", unsafe_allow_html=True)

# ── Session state defaults ──
for _k, _v in [("active_symbol","NIFTY 50"), ("chart_tf","5m"), ("_wl_selected",None)]:
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ── Helpers ──
def _make_sym(name: str) -> dict:
    n = name.strip().upper()
    yf = {"NIFTY":"^NSEI","BANKNIFTY":"^NSEBANK","SENSEX":"^BSESN"}.get(n, f"{n}.NS")
    return {"yf": yf, "nse": n, "tv": f"NSE:{n}"}

def _find_symbol_candidates(query: str) -> list:
    q = query.strip().upper()
    if not q: return []
    seen, results = set(), []
    def _add(k):
        if k not in seen: seen.add(k); results.append(k)
    for k in SYMBOLS:
        if q == k.upper() or q == SYMBOLS[k].get("nse","").upper(): _add(k)
    if results: return results
    if q in SYMBOL_ALIASES:
        for k in SYMBOLS:
            if k == SYMBOL_ALIASES[q]: _add(k)
    if results: return results
    for k in SYMBOLS:
        n = SYMBOLS[k].get("nse","").upper()
        if k.upper().startswith(q) or n.startswith(q): _add(k)
    for k in SYMBOLS:
        n = SYMBOLS[k].get("nse","").upper()
        if q in k.upper() or q in n: _add(k)
    return results[:10]

def _atm_strike(price: float) -> int:
    if price <= 0: return 0
    step = 2.5 if price < 50 else (5 if price < 250 else (10 if price < 1000 else (50 if price < 5000 else 100)))
    return int(round(price / step) * step)

def _pct_color(pct: float) -> str:
    return "#4caf50" if pct >= 0 else "#f44336"

def make_sparkline(prices: list, color="#4caf50", w=60, h=22) -> str:
    if not prices or len(prices) < 2: return f'<svg width="{w}" height="{h}"></svg>'
    lo, hi = min(prices), max(prices)
    if hi == lo: hi = lo + 0.01
    n = len(prices) - 1
    pts = [f"{round(i*w/n,1)},{round((1-(p-lo)/(hi-lo))*(h-2)+1,1)}" for i, p in enumerate(prices)]
    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}"><polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="1.5" stroke-linejoin="round"/></svg>'

def _news_sentiment(headline: str) -> dict:
    t = headline.lower()
    bull = sum(1 for k in ["gain","rise","rally","up","surge","positive","growth","beat","strong","buy","bull","recover","boost","jump","soar"] if k in t)
    bear = sum(1 for k in ["fall","drop","decline","down","loss","weak","crash","cut","sell","bear","concern","slump","plunge","dip"] if k in t)
    hi = any(k in t for k in ["rbi","fed","rate","gdp","inflation","budget","election","sebi","fii","ipo","earnings"])
    return {"sentiment": "BULLISH" if bull>bear else ("BEARISH" if bear>bull else "NEUTRAL"),
            "impact": "HIGH IMPACT" if hi else ("MEDIUM IMPACT" if (bull+bear)>=2 else "LOW IMPACT")}

def _ai_action(headline: str) -> str:
    h = headline.lower()
    if "rbi" in h and ("rate" in h or "policy" in h): return "Monitor rate-sensitive sectors — banking, NBFCs, autos."
    if "inflation" in h: return "Inflation data may pressure RBI stance. Watch bond yields and NBFC stocks."
    if "fii" in h and ("buy" in h or "inflow" in h): return "FII inflows support index. Track large-cap momentum."
    if "result" in h or "earnings" in h: return "Post-results volatility likely. Monitor IV and ATM strikes."
    if "crude" in h or "oil" in h: return "Oil move impacts OMCs, airlines, paint cos."
    return "Monitor related stocks for breakout/breakdown setups."


# ── Cached loaders ──
_mkt_open_now = is_market_open()

@st.cache_data(ttl=45 if _mkt_open_now else 300)
def _load_indices():
    return get_nse_indices()

@st.cache_data(ttl=600)
def _load_news():
    return scrape_moneycontrol_news()

@st.cache_data(ttl=30 if _mkt_open_now else 300)
def _load_wl_prices(symbols_tuple):
    results = {}
    def _f(name):
        try:
            sym = SYMBOLS.get(name, _make_sym(name))
            return name, get_spot_price(sym["yf"], sym.get("nse",""))
        except Exception:
            return name, None
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_f, n): n for n in symbols_tuple}
        try:
            for fut in concurrent.futures.as_completed(futs, timeout=15):
                try:
                    n, p = fut.result()
                    results[n] = p
                except Exception:
                    pass
        except concurrent.futures.TimeoutError:
            for fut, name in futs.items():
                if fut.done():
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
            sym = SYMBOLS.get(name, _make_sym(name))
            return name, get_sparkline_data(sym["yf"])
        except Exception:
            return name, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(_f, n): n for n in symbols_tuple}
        try:
            for fut in concurrent.futures.as_completed(futs, timeout=15):
                try:
                    n, pts = fut.result()
                    results[n] = pts
                except Exception:
                    pass
        except concurrent.futures.TimeoutError:
            for fut, name in futs.items():
                if fut.done():
                    try:
                        n, pts = fut.result()
                        results[n] = pts
                    except Exception:
                        pass
    return results

@st.cache_data(ttl=20 if _mkt_open_now else 300)
def _load_spot_and_df(yf_sym, nse_sym, timeframe):
    period, interval = {"1m":("1d","1m"),"3m":("1d","2m"),"5m":("1d","5m"),
                        "15m":("5d","15m"),"1h":("5d","60m"),"1D":("1mo","1d")}.get(timeframe, ("1d","5m"))
    spot, df = None, pd.DataFrame()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            pf = ex.submit(get_spot_price, yf_sym, nse_sym)
            df_f = ex.submit(get_intraday_data, yf_sym, period, interval)
            spot = pf.result(timeout=10)
            df = df_f.result(timeout=10)
    except Exception:
        pass
    return spot, df if df is not None else pd.DataFrame()

@st.cache_data(ttl=120 if _mkt_open_now else 600)
def _load_option_chain(nse_sym):
    return get_option_chain_nse_direct(nse_sym)


# ── Resolve active symbol ──
if st.session_state._wl_selected:
    st.session_state.active_symbol = st.session_state._wl_selected
    st.session_state._wl_selected = None

active_sym_key = st.session_state.active_symbol
active_sym = SYMBOLS.get(active_sym_key, _make_sym(active_sym_key))

# ── Top bar ──
indices_data = _load_indices()
now_ist = datetime.now(IST)
mkt_open = is_market_open()
mkt_color = "#4caf50" if mkt_open else "#ef4444"
mkt_text  = "LIVE" if mkt_open else "CLOSED"

def _idx_pill(label, key):
    d = indices_data.get(key, {})
    if not d or not d.get("price"):
        return f'<span style="color:#4b5563;font-size:0.78em;white-space:nowrap;">{label} --</span>'
    p, pct = d["price"], d.get("pct", 0)
    c = _pct_color(pct)
    return (f'<span style="color:#9ca3af;font-size:0.7em;">{label}</span>&nbsp;'
            f'<span style="color:#e8e8e8;font-weight:600;font-size:0.8em;">{p:,.2f}</span>&nbsp;'
            f'<span style="color:{c};font-size:0.7em;">{"+" if pct>=0 else ""}{pct:.2f}%</span>')

st.markdown(f"""
<div style="background:#141428;border-bottom:1px solid #2a2a4a;padding:5px 14px;
            display:flex;align-items:center;gap:16px;overflow-x:auto;white-space:nowrap;min-height:34px;">
  <span style="background:{mkt_color};color:white;padding:2px 9px;border-radius:20px;font-size:0.62em;font-weight:700;flex-shrink:0;">● {mkt_text}</span>
  {_idx_pill("NIFTY","NIFTY 50")}
  <span style="color:#2a2a4a;">│</span>
  {_idx_pill("BANK","BANK NIFTY")}
  <span style="color:#2a2a4a;">│</span>
  {_idx_pill("VIX","INDIA VIX")}
  <span style="margin-left:auto;color:#4b5563;font-size:0.62em;flex-shrink:0;">{now_ist.strftime("%-d %b · %I:%M %p IST")}</span>
</div>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════
#  3-COLUMN LAYOUT: Left | Center | Right
# ═══════════════════════════════════════════════
left_col, center_col, right_col = st.columns([4, 14, 7])


# ══════════════════════════════════════════════
#  LEFT: Watchlist
# ══════════════════════════════════════════════
with left_col:
    st.markdown(f"""
<div style="padding:9px 10px 7px;border-bottom:1px solid #2a2a4a;background:#141428;">
  <span style="color:#e8e8e8;font-size:0.95em;font-weight:700;">Options Terminal</span><br>
  <span style="color:#4b5563;font-size:0.6em;">NSE · BSE · MCX &nbsp;
  <span style="color:{mkt_color};font-weight:700;">{mkt_text}</span> &nbsp;
  <span style="color:#f59e0b;">{get_market_opens_in()}</span></span>
</div>""", unsafe_allow_html=True)

    saved_watchlist = get_watchlist()
    if not saved_watchlist:
        for d in ["NIFTY 50","BANK NIFTY","RELIANCE","HDFC BANK","TCS","INFOSYS","IDEA"]:
            add_to_watchlist(d)
        saved_watchlist = get_watchlist()

    wl_prices = _load_wl_prices(tuple(saved_watchlist)) if saved_watchlist else {}
    wl_sparklines = {}

    st.markdown('<div style="padding:5px 8px;border-bottom:1px solid #2a2a4a;"><span style="color:#6b7280;font-size:0.56em;text-transform:uppercase;letter-spacing:1px;font-weight:600;">WATCHLIST</span></div>', unsafe_allow_html=True)

    sym_search = st.text_input("Search", placeholder="Search eg. NIFTY, RELIANCE...", key="wl_search", label_visibility="collapsed")
    if sym_search.strip():
        candidates = _find_symbol_candidates(sym_search.strip())
        if len(candidates) == 1:
            st.session_state.active_symbol = candidates[0]; st.rerun()
        elif candidates:
            sel = st.selectbox("Select", candidates, key="search_pick", label_visibility="collapsed")
            if st.button("Load", key="load_search", use_container_width=True):
                st.session_state.active_symbol = sel; st.rerun()

    for wl_name in saved_watchlist:
        sym_info  = SYMBOLS.get(wl_name, {})
        nse_s     = sym_info.get("nse", wl_name)
        disp      = SYMBOL_SHORT.get(wl_name, (nse_s, wl_name))[0]
        full_name = SYMBOL_SHORT.get(wl_name, ("", wl_name))[1]
        p = wl_prices.get(wl_name)
        if p:
            price_str = f"{p:,.2f}"
            pct_str   = ""
            clr = "#4caf50"
        else:
            price_str, pct_str, clr = "--", "", "#6b7280"
        spark_svg = ""
        is_active = (wl_name == active_sym_key)
        left_bar  = "3px solid #387ed1" if is_active else "3px solid transparent"
        row_bg    = "rgba(56,126,209,0.06)" if is_active else "transparent"

        r_cols = st.columns([11, 1])
        with r_cols[0]:
            if st.button(f"{disp}　　{price_str}", key=f"wl_{wl_name}", use_container_width=True):
                st.session_state._wl_selected = wl_name; st.rerun()
        with r_cols[1]:
            if st.button("×", key=f"wl_del_{wl_name}"):
                remove_from_watchlist(wl_name); st.rerun()
        st.markdown(
            f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f'padding:0 4px 5px;border-left:{left_bar};background:{row_bg};">'
            f'<span style="color:#4b5563;font-size:0.62em;">{full_name}</span>'
            f'<span style="display:flex;align-items:center;gap:4px;">{spark_svg}'
            f'<span style="color:{clr};font-size:0.68em;font-weight:600;">{pct_str}</span></span></div>',
            unsafe_allow_html=True,
        )

    wl_input = st.text_input("Add", placeholder="+ IDEA  or  - COFORGE", key="wl_input", label_visibility="collapsed")
    if wl_input.strip():
        inp = wl_input.strip()
        if inp.startswith("-"):
            remove_from_watchlist(inp.lstrip("- ").upper()); st.rerun()
        else:
            sym_to_add = inp.lstrip("+ ").upper()
            candidates = _find_symbol_candidates(sym_to_add)
            add_to_watchlist(candidates[0] if candidates else sym_to_add); st.rerun()


# ══════════════════════════════════════════════
#  CENTER: Symbol Header + TV Chart + Indicators
# ══════════════════════════════════════════════
with center_col:
    spot_price, df = _load_spot_and_df(active_sym["yf"], active_sym.get("nse",""), st.session_state.chart_tf)
    data_ok = (spot_price is not None) and (df is not None) and (not df.empty)

    # Indicators & signals
    action, signal = "HOLD", {"action":"HOLD","buy_count":0,"sell_count":0,"target":None,"stop_loss":None}
    rsi_d = macd_d = st_d = vwap_d = oi_d = None
    all_signals, option_rec = [], None

    if data_ok:
        try:
            rsi_d   = compute_rsi(df)
            macd_d  = compute_macd(df)
            st_d    = compute_supertrend(df)
            vwap_d  = compute_vwap(df)
            oi_d    = evaluate_oi(None)
            signal  = generate_signal(rsi_d, macd_d, st_d, vwap_d, oi_d, spot_price)
            all_signals = compute_all_signals(df, st.session_state.chart_tf)
            action  = signal["action"]
            nse_sym = active_sym.get("nse","")
            if action in ("BUY","SELL") and nse_sym:
                try: option_rec = get_option_recommendation(nse_sym, spot_price, action)
                except: pass
        except Exception:
            pass

    # Auto signal → trade → SMS (15-min cooldown)
    if data_ok and action in ("BUY","SELL") and is_market_open():
        akey  = f"last_auto_signal_{active_sym_key}"
        ckey  = f"last_signal_time_{active_sym_key}"
        last_a = st.session_state.get(akey)
        last_t = st.session_state.get(ckey)
        cooldown_ok = not last_t or (datetime.now(IST) - last_t).total_seconds() >= 900
        if action != last_a and cooldown_ok:
            st.session_state[akey] = action
            st.session_state[ckey] = datetime.now(IST)
            opt_t = "CE" if action == "BUY" else "PE"
            if option_rec:
                auto_trade = create_trade(
                    instrument=active_sym_key, strike=option_rec["strike"],
                    option_type=opt_t, expiry=option_rec["expiry"],
                    entry_price=option_rec["ltp"], target_price=option_rec["premium_target"],
                    stop_loss=option_rec["premium_sl"], quantity=1, lot_size=option_rec["lot_size"],
                )
            else:
                auto_trade = create_trade(
                    instrument=active_sym_key, strike=round(spot_price/100)*100,
                    option_type=opt_t, expiry="Weekly", entry_price=spot_price,
                    target_price=signal["target"] or round(spot_price*1.01,2),
                    stop_loss=signal["stop_loss"] or round(spot_price*0.997,2),
                    quantity=1, lot_size=1,
                )
            send_sms_to_all(auto_trade, action="BUY")
            if EMAIL_SENDER and EMAIL_RECEIVER:
                send_signal_email(EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER, active_sym_key, signal, option_rec)

    # Auto-close trades on SL/Target
    for t in get_open_trades():
        t_sym = SYMBOLS.get(t["instrument"], {})
        t_nse = t_sym.get("nse","")
        if not t_nse: continue
        cur_ltp = get_current_option_ltp(t_nse, t["strike"], t["option_type"], t["expiry"])
        if cur_ltp is None: continue
        if t["stop_loss"] > 0 and cur_ltp <= t["stop_loss"]:
            closed = close_trade(t["id"], cur_ltp)
            if closed: send_sms_to_all(closed, action="EXIT")
        elif t["target_price"] > 0 and cur_ltp >= t["target_price"]:
            closed = close_trade(t["id"], cur_ltp)
            if closed: send_sms_to_all(closed, action="EXIT")

    # ── Symbol header ──
    if data_ok:
        day_chg = df["Close"].iloc[-1] - df["Open"].iloc[0]
        day_pct = (day_chg / df["Open"].iloc[0]) * 100
        chg_c = _pct_color(day_pct)
        arrow  = "▲" if day_chg >= 0 else "▼"
        disp_short = SYMBOL_SHORT.get(active_sym_key, (active_sym_key,))[0]
        action_pill = (
            "<div style='background:#1a3a2a;color:#4caf50;padding:2px 8px;border-radius:4px;font-size:0.68em;font-weight:700;display:inline-block;'>▲ BUY</div>" if action=="BUY" else
            "<div style='background:#3a1a1a;color:#ef4444;padding:2px 8px;border-radius:4px;font-size:0.68em;font-weight:700;display:inline-block;'>▼ SELL</div>" if action=="SELL" else
            "<div style='background:#1a1a2e;color:#9ca3af;padding:2px 8px;border-radius:4px;font-size:0.68em;font-weight:600;display:inline-block;'>⏸ HOLD</div>"
        )
        st.markdown(f"""
<div style="display:flex;justify-content:space-between;align-items:flex-start;padding:7px 4px 9px;border-bottom:1px solid #2a2a4a;">
  <div>
    <div style="display:flex;align-items:baseline;gap:8px;">
      <span style="color:#e8e8e8;font-size:1.25em;font-weight:700;">{disp_short}</span>
      <span style="color:#6b7280;font-size:0.7em;">NSE</span>
    </div>
    <div style="display:flex;align-items:baseline;gap:8px;margin-top:2px;">
      <span style="color:#e8e8e8;font-size:1.55em;font-weight:700;">{spot_price:,.2f}</span>
      <span style="color:{chg_c};font-size:0.88em;font-weight:600;">{arrow} {abs(day_chg):,.2f} ({"+" if day_pct>=0 else ""}{day_pct:.2f}%)</span>
    </div>
  </div>
  <div style="text-align:right;padding-top:4px;">
    <div style="color:#6b7280;font-size:0.6em;">O: {df['Open'].iloc[0]:,.2f} &nbsp; H: {df['High'].max():,.2f} &nbsp; L: {df['Low'].min():,.2f}</div>
    <div style="margin-top:4px;">{action_pill}</div>
  </div>
</div>""", unsafe_allow_html=True)
    else:
        st.markdown(f'<div style="padding:7px 4px 9px;border-bottom:1px solid #2a2a4a;"><span style="color:#e8e8e8;font-size:1.2em;font-weight:700;">{active_sym_key}</span> <span style="color:#f59e0b;font-size:0.8em;">⟳ Loading...</span></div>', unsafe_allow_html=True)

    # ── Timeframe selector ──
    tf_col, _spacer = st.columns([4, 6])
    with tf_col:
        new_tf = st.radio("tf", ["1m","3m","5m","15m","1h","1D"],
            index=["1m","3m","5m","15m","1h","1D"].index(st.session_state.chart_tf),
            horizontal=True, key="tf_radio", label_visibility="collapsed")
        if new_tf != st.session_state.chart_tf:
            st.session_state.chart_tf = new_tf; st.cache_data.clear(); st.rerun()

    # ── Plotly Candlestick Chart (no deprecated APIs) ──
    import plotly.graph_objects as go

    if data_ok and df is not None and not df.empty:
        _df = df.copy()
        _colors = [
            "rgba(76,175,80,0.45)" if c >= o else "rgba(244,67,54,0.45)"
            for c, o in zip(_df["Close"], _df["Open"])
        ]
        _fig = go.Figure()
        _fig.add_trace(go.Candlestick(
            x=_df.index, open=_df["Open"], high=_df["High"],
            low=_df["Low"], close=_df["Close"], name=active_sym_key,
            increasing=dict(line=dict(color="#4caf50"), fillcolor="#4caf50"),
            decreasing=dict(line=dict(color="#ef4444"), fillcolor="#ef4444"),
            showlegend=False,
        ))
        if "Volume" in _df.columns:
            _fig.add_trace(go.Bar(
                x=_df.index, y=_df["Volume"], marker_color=_colors,
                name="Vol", yaxis="y2", showlegend=False,
            ))
        if spot_price:
            _fig.add_hline(y=spot_price, line_dash="dot", line_color="#387ed1", line_width=1)
        _fig.update_layout(
            paper_bgcolor="#131722", plot_bgcolor="#131722",
            font=dict(color="#9ca3af", size=11),
            xaxis=dict(
                rangeslider=dict(visible=False), gridcolor="#1a1a2e",
                showgrid=True, color="#6b7280", tickfont=dict(size=10),
            ),
            yaxis=dict(
                gridcolor="#1a1a2e", side="right", color="#6b7280",
                tickfont=dict(size=10), domain=[0.22, 1.0],
            ),
            yaxis2=dict(
                overlaying="y", side="right", showgrid=False,
                showticklabels=False, domain=[0.0, 0.18],
            ),
            margin=dict(l=0, r=55, t=8, b=25),
            height=452,
        )
        st.plotly_chart(_fig, use_container_width=True,
                        config={"displayModeBar": False, "scrollZoom": True},
                        key="main_chart")
    else:
        st.markdown(
            '<div style="height:452px;background:#131722;border-radius:8px;'
            'display:flex;align-items:center;justify-content:center;'
            'color:#4b5563;font-size:0.85em;">Fetching chart data…</div>',
            unsafe_allow_html=True,
        )

    # ── Indicators row ──
    if data_ok and rsi_d:
        rsi_val = rsi_d.get("value", 50) or 50
        rsi_c   = "#ef4444" if rsi_val > 70 else ("#4caf50" if rsi_val < 30 else "#e8e8e8")
        rsi_lbl = "OB" if rsi_val > 70 else ("OS" if rsi_val < 30 else "N")
        macd_sig = macd_d.get("signal","") if macd_d else ""
        macd_c   = "#4caf50" if macd_sig=="BUY" else ("#ef4444" if macd_sig=="SELL" else "#9ca3af")
        st_sig   = "▲ BULL" if (st_d and st_d.get("direction")==1) else "▼ BEAR"
        st_c     = "#4caf50" if (st_d and st_d.get("direction")==1) else "#ef4444"
        vwap_sig = vwap_d.get("signal","") if vwap_d else ""
        vwap_c   = "#4caf50" if vwap_sig=="BUY" else ("#ef4444" if vwap_sig=="SELL" else "#9ca3af")

        st.markdown(f"""
<div style="display:flex;gap:8px;padding:7px 4px;border-top:1px solid #2a2a4a;flex-wrap:wrap;">
  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:5px;padding:5px 9px;flex:1;min-width:75px;">
    <div style="color:#6b7280;font-size:0.55em;text-transform:uppercase;">RSI(14)</div>
    <div style="color:{rsi_c};font-size:0.9em;font-weight:700;">{rsi_val:.1f} <span style="font-size:0.72em;">{rsi_lbl}</span></div>
  </div>
  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:5px;padding:5px 9px;flex:1;min-width:75px;">
    <div style="color:#6b7280;font-size:0.55em;text-transform:uppercase;">MACD</div>
    <div style="color:{macd_c};font-size:0.9em;font-weight:700;">{macd_sig or "--"}</div>
  </div>
  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:5px;padding:5px 9px;flex:1;min-width:75px;">
    <div style="color:#6b7280;font-size:0.55em;text-transform:uppercase;">SUPERTREND</div>
    <div style="color:{st_c};font-size:0.9em;font-weight:700;">{st_sig}</div>
  </div>
  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:5px;padding:5px 9px;flex:1;min-width:75px;">
    <div style="color:#6b7280;font-size:0.55em;text-transform:uppercase;">VWAP</div>
    <div style="color:{vwap_c};font-size:0.9em;font-weight:700;">{vwap_sig or "--"}</div>
  </div>
  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:5px;padding:5px 9px;flex:1;min-width:75px;">
    <div style="color:#6b7280;font-size:0.55em;text-transform:uppercase;">SIGNAL</div>
    <div style="color:{"#4caf50" if action=="BUY" else "#ef4444" if action=="SELL" else "#9ca3af"};font-size:0.9em;font-weight:700;">{action}</div>
  </div>
</div>""", unsafe_allow_html=True)
    else:
        st.markdown('<div style="padding:7px 4px;border-top:1px solid #2a2a4a;color:#4b5563;font-size:0.72em;">Indicators loading...</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════
#  RIGHT: Option Chain
# ══════════════════════════════════════════════
with right_col:
    nse_sym_oc = active_sym.get("nse","")
    st.markdown('<div style="padding:6px 4px 5px;border-bottom:1px solid #2a2a4a;"><span style="color:#6b7280;font-size:0.6em;text-transform:uppercase;letter-spacing:1px;font-weight:600;">OPTION CHAIN</span></div>', unsafe_allow_html=True)

    if not nse_sym_oc:
        st.info("Option chain not available for this instrument.")
    else:
        oc_raw = _load_option_chain(nse_sym_oc)
        if oc_raw is None or "records" not in oc_raw:
            from dhan_api import _is_configured as _dhan_cfg
            if not _dhan_cfg():
                st.markdown(
                    '<div style="background:#1a1200;border:1px solid #78350f;border-radius:6px;padding:10px;margin:6px 0;">'
                    '<div style="color:#fbbf24;font-size:0.72em;font-weight:700;">⚠ Dhan Token Expired</div>'
                    '<div style="color:#9ca3af;font-size:0.68em;margin-top:4px;">Go to <b>SMS Admin → Dhan API Token</b> and paste a fresh token from web.dhan.co</div>'
                    '</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div style="color:#f59e0b;font-size:0.76em;padding:8px 2px;">⟳ Loading option chain for {nse_sym_oc}...</div>', unsafe_allow_html=True)
            if st.button("Retry", key="oc_retry"):
                st.cache_data.clear(); st.rerun()
        else:
            records      = oc_raw["records"]
            expiry_dates = records.get("expiryDates", [])
            chain_data   = records.get("data", [])
            spot_oc = spot_price if data_ok and spot_price else records.get("underlyingValue", 0) or 0

            selected_expiry = st.selectbox("Expiry", expiry_dates, index=0, key="oc_exp", label_visibility="collapsed")

            stats = compute_option_stats(chain_data, selected_expiry, spot_oc)
            pcr_c = "#4caf50" if stats["pcr_label"]=="BULLISH" else ("#ef4444" if stats["pcr_label"]=="BEARISH" else "#9ca3af")

            st.markdown(f"""
<div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-bottom:7px;">
  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:5px;padding:5px 7px;">
    <div style="color:#6b7280;font-size:0.52em;text-transform:uppercase;">SPOT</div>
    <div style="color:#e8e8e8;font-size:0.9em;font-weight:700;">{spot_oc:,.0f}</div>
  </div>
  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:5px;padding:5px 7px;">
    <div style="color:#6b7280;font-size:0.52em;text-transform:uppercase;">PCR</div>
    <div style="color:{pcr_c};font-size:0.9em;font-weight:700;">{stats["pcr"]}</div>
  </div>
  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:5px;padding:5px 7px;">
    <div style="color:#6b7280;font-size:0.52em;text-transform:uppercase;">MAX PAIN</div>
    <div style="color:#fbbf24;font-size:0.9em;font-weight:700;">{stats["max_pain"]:,}</div>
  </div>
  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:5px;padding:5px 7px;">
    <div style="color:#6b7280;font-size:0.52em;text-transform:uppercase;">SIGNAL</div>
    <div style="color:{pcr_c};font-size:0.82em;font-weight:600;">{stats["pcr_label"]}</div>
  </div>
</div>""", unsafe_allow_html=True)

            # Build chain rows ATM ± 8
            chain_rows, all_strikes = [], set()
            for item in chain_data:
                if item.get("expiryDate") != selected_expiry: continue
                strike = item.get("strikePrice", 0)
                all_strikes.add(strike)
                ce, pe = item.get("CE",{}), item.get("PE",{})
                chain_rows.append({
                    "strike": strike,
                    "ce_oi": ce.get("openInterest",0),
                    "ce_oi_chg": ce.get("changeinOpenInterest",0),
                    "ce_ltp": ce.get("lastPrice",0),
                    "pe_ltp": pe.get("lastPrice",0),
                    "pe_oi": pe.get("openInterest",0),
                    "pe_oi_chg": pe.get("changeinOpenInterest",0),
                })
            chain_rows.sort(key=lambda r: r["strike"])
            atm = min(all_strikes, key=lambda s: abs(s-spot_oc)) if all_strikes and spot_oc > 0 else 0

            if atm > 0:
                sorted_s = sorted(all_strikes)
                ai = sorted_s.index(atm) if atm in sorted_s else len(sorted_s)//2
                visible = set(sorted_s[max(0,ai-8): ai+9])
                chain_rows = [r for r in chain_rows if r["strike"] in visible]

            max_ce_oi = max((r["ce_oi"] for r in chain_rows), default=1) or 1
            max_pe_oi = max((r["pe_oi"] for r in chain_rows), default=1) or 1

            if chain_rows:
                tbl = '<table style="width:100%;border-collapse:collapse;font-size:0.7em;">'
                tbl += ('<thead><tr style="background:#1e293b;">'
                        '<th style="padding:3px;color:#22c55e;text-align:right;">CE OI</th>'
                        '<th style="padding:3px;color:#22c55e;text-align:right;">LTP</th>'
                        '<th style="padding:3px 4px;color:#fbbf24;text-align:center;background:#1a1a2e;">STRIKE</th>'
                        '<th style="padding:3px;color:#ef4444;text-align:left;">LTP</th>'
                        '<th style="padding:3px;color:#ef4444;text-align:left;">PE OI</th>'
                        '</tr></thead><tbody>')

                for r in chain_rows:
                    is_atm    = r["strike"] == atm
                    is_itm_ce = spot_oc > 0 and r["strike"] < spot_oc
                    is_itm_pe = spot_oc > 0 and r["strike"] > spot_oc
                    atm_bg = "background:rgba(251,191,36,0.1);border-top:1px solid rgba(251,191,36,0.25);border-bottom:1px solid rgba(251,191,36,0.25);" if is_atm else ""
                    ce_bg  = "background:rgba(34,197,94,0.05);" if is_itm_ce else ""
                    pe_bg  = "background:rgba(239,68,68,0.05);" if is_itm_pe else ""

                    cb = max(3, int(r["ce_oi"] / max_ce_oi * 48))
                    pb = max(3, int(r["pe_oi"] / max_pe_oi * 48))

                    tbl += '<tr style="border-bottom:1px solid rgba(42,42,74,0.2);">'
                    tbl += (f'<td style="padding:3px;{ce_bg}{atm_bg}">'
                            f'<div style="display:flex;align-items:center;justify-content:flex-end;gap:2px;">'
                            f'<span style="color:#d1d5db;">{_fmt_oi(r["ce_oi"])}</span>'
                            f'<div style="width:{cb}px;height:5px;background:#22c55e;border-radius:2px;opacity:0.7;"></div>'
                            f'</div></td>')
                    tbl += f'<td style="padding:3px;color:#22c55e;font-weight:600;text-align:right;{ce_bg}{atm_bg}">{r["ce_ltp"]:.1f}</td>'
                    tbl += f'<td style="padding:3px 4px;color:#fbbf24;font-weight:700;text-align:center;background:#1a1a2e;{atm_bg}">{int(r["strike"]):,}{"★" if is_atm else ""}</td>'
                    tbl += f'<td style="padding:3px;color:#ef4444;font-weight:600;{pe_bg}{atm_bg}">{r["pe_ltp"]:.1f}</td>'
                    tbl += (f'<td style="padding:3px;{pe_bg}{atm_bg}">'
                            f'<div style="display:flex;align-items:center;gap:2px;">'
                            f'<div style="width:{pb}px;height:5px;background:#ef4444;border-radius:2px;opacity:0.7;"></div>'
                            f'<span style="color:#d1d5db;">{_fmt_oi(r["pe_oi"])}</span>'
                            f'</div></td>')
                    tbl += '</tr>'

                tbl += '</tbody></table>'
                st.markdown(tbl, unsafe_allow_html=True)
                src = oc_raw.get("_source","NSE")
                st.caption(f"ATM {int(atm):,} · CE {_fmt_oi(stats['total_ce_oi'])} · PE {_fmt_oi(stats['total_pe_oi'])} · {src.upper()}")


# ══════════════════════════════════════════════
#  BOTTOM TABS: AI News + SMS Admin
# ══════════════════════════════════════════════
news_data = _load_news()
tab_news, tab_sms = st.tabs([f"AI News  {len(news_data)}", "SMS Admin"])


with tab_news:
    news_col, sent_col = st.columns([7, 3])

    with news_col:
        st.markdown('<div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;"><span style="background:#6366f1;color:white;padding:2px 8px;border-radius:4px;font-size:0.7em;font-weight:700;">AI</span><span style="color:#e8e8e8;font-size:0.9em;font-weight:600;">Intel Feed</span><span style="background:#ef4444;color:white;padding:1px 6px;border-radius:20px;font-size:0.58em;font-weight:700;">LIVE</span></div>', unsafe_allow_html=True)
        filter_choice = st.radio("filter", [f"All  {len(news_data)}", "Bullish", "Bearish", "High impact"],
                                  horizontal=True, key="news_filter_radio", label_visibility="collapsed")
        if news_data:
            for article in news_data[:8]:
                headline  = article.get("headline","")
                url       = article.get("url","")
                summary   = article.get("summary", headline[:120])
                analysis  = _news_sentiment(headline)
                sentiment = article.get("sentiment", analysis["sentiment"]).upper()
                impact    = analysis["impact"]
                if "Bullish" in filter_choice and sentiment != "BULLISH": continue
                if "Bearish" in filter_choice and sentiment != "BEARISH": continue
                if "High impact" in filter_choice and "HIGH" not in impact: continue
                sent_c = "#4caf50" if sentiment=="BULLISH" else ("#ef4444" if sentiment=="BEARISH" else "#9ca3af")
                imp_c  = "#ef4444" if "HIGH" in impact else ("#f59e0b" if "MEDIUM" in impact else "#6b7280")
                link   = f'<a href="{url}" target="_blank" style="color:#60a5fa;font-size:0.68em;text-decoration:none;">Read →</a>' if url else ""
                st.markdown(f"""
<div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:10px 12px;margin:5px 0;border-left:3px solid {sent_c};">
  <div style="display:flex;gap:8px;margin-bottom:4px;">
    <span style="color:{sent_c};font-size:0.62em;font-weight:700;">{sentiment}</span>
    <span style="color:{imp_c};font-size:0.62em;">{impact}</span>
  </div>
  <div style="color:#e8e8e8;font-size:0.84em;font-weight:600;line-height:1.4;">{headline}</div>
  <div style="color:#9ca3af;font-size:0.75em;line-height:1.5;margin-top:4px;">{summary}</div>
  <div style="background:#1a1a2e;border-left:2px solid #387ed1;padding:5px 8px;margin:5px 0;border-radius:0 4px 4px 0;">
    <div style="color:#387ed1;font-size:0.58em;font-weight:700;text-transform:uppercase;">AI ACTION</div>
    <div style="color:#d1d5db;font-size:0.74em;">{_ai_action(headline)}</div>
  </div>
  <div style="display:flex;justify-content:space-between;margin-top:2px;">
    <span style="color:#4b5563;font-size:0.6em;">{article.get("source","")}</span>{link}
  </div>
</div>""", unsafe_allow_html=True)
        else:
            st.info("News loading... refreshes every 5 minutes.")

    with sent_col:
        sent_score = 50
        if data_ok and rsi_d and st_d and vwap_d:
            rsi_val2 = rsi_d.get("value",50) or 50
            sent_score = min(100, max(0,
                int((rsi_val2-30)/40*25) +
                (25 if (st_d and st_d.get("direction")==1) else 0) +
                (25 if (vwap_d and vwap_d.get("signal")=="BUY") else 0) +
                (0 if not oi_d else min(25, max(0, int(oi_d.get("pcr",0.8)*25))))
            ))
        sent_label = "RISK-ON" if sent_score>=60 else ("RISK-OFF" if sent_score<=40 else "NEUTRAL")
        sent_clr   = "#4caf50" if sent_score>=60 else ("#ef4444" if sent_score<=40 else "#f59e0b")

        st.markdown(f"""
<div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:12px;margin-bottom:10px;">
  <div style="color:#6b7280;font-size:0.6em;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px;">MARKET SENTIMENT</div>
  <div style="font-size:2.1em;font-weight:700;color:#e8e8e8;">{sent_score}<span style="font-size:0.4em;color:#6b7280;"> / 100</span></div>
  <div style="background:linear-gradient(to right,#ef4444 0%,#fbbf24 50%,#4caf50 100%);height:5px;border-radius:3px;margin:7px 0;position:relative;">
    <div style="position:absolute;left:{sent_score}%;top:-3px;width:4px;height:11px;background:white;border-radius:2px;transform:translateX(-50%);"></div>
  </div>
  <div style="display:flex;justify-content:space-between;margin-bottom:6px;">
    <span style="font-size:0.58em;color:#ef4444;">Bearish</span>
    <span style="font-size:0.58em;color:#4caf50;">Bullish</span>
  </div>
  <div style="color:{sent_clr};font-size:0.7em;font-weight:700;">{sent_label}</div>
</div>""", unsafe_allow_html=True)

        open_trades = get_open_trades()
        st.markdown('<div style="color:#6b7280;font-size:0.6em;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px;">ACTIVE SIGNALS</div>', unsafe_allow_html=True)
        if open_trades:
            for t in open_trades[:4]:
                sig_c  = "#4caf50" if t.get("option_type")=="CE" else "#ef4444"
                sig_l  = "BULLISH" if t.get("option_type")=="CE" else "BEARISH"
                contract = f"{t.get('instrument','')} {t.get('strike','')} {t.get('option_type','')}"
                st.markdown(f"""
<div style="background:#12121f;border:1px solid #2a2a4a;border-radius:5px;padding:8px;margin:3px 0;border-left:3px solid {sig_c};">
  <div style="color:{sig_c};font-size:0.64em;font-weight:700;margin-bottom:2px;">{sig_l}</div>
  <div style="color:#e8e8e8;font-size:0.78em;font-weight:600;">{contract}</div>
  <div style="display:flex;gap:10px;margin-top:3px;font-size:0.65em;color:#6b7280;">
    <span>E <span style="color:#e8e8e8;">{t.get('entry_price',0)}</span></span>
    <span>SL <span style="color:#ef4444;">{t.get('stop_loss',0)}</span></span>
    <span>T <span style="color:#4caf50;">{t.get('target_price',0)}</span></span>
  </div>
</div>""", unsafe_allow_html=True)
        else:
            st.markdown('<div style="color:#4b5563;font-size:0.75em;padding:6px 0;">No active signals.</div>', unsafe_allow_html=True)

        if data_ok and rsi_d:
            st.markdown('<div style="color:#6b7280;font-size:0.6em;text-transform:uppercase;letter-spacing:1px;margin:10px 0 4px;">CLAUDE ANALYSIS</div>', unsafe_allow_html=True)
            with st.spinner("AI analyzing..."):
                try:
                    analysis_text = analyze_market(
                        {"nifty": spot_price if active_sym.get("nse")=="NIFTY" else None,
                         "banknifty": spot_price if active_sym.get("nse")=="BANKNIFTY" else None},
                        signal, rsi_d, macd_d, st_d, vwap_d, oi_d, news_data,
                    )
                except Exception:
                    analysis_text = "Analysis unavailable — check ANTHROPIC_API_KEY."
            st.markdown(f'<div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:10px;"><p style="color:#d1d5db;font-size:0.8em;line-height:1.7;margin:0;">{analysis_text}</p></div>', unsafe_allow_html=True)


with tab_sms:
    if st.session_state.get("kite_just_connected"):
        st.session_state.pop("kite_just_connected", None)

    # ── Dhan Token Update ──────────────────────────────────────────
    import dhan_api as _dhan
    _dhan_ok = _dhan._is_configured()
    _dhan_icon = "🟢" if _dhan_ok else "🔴"
    with st.expander(f"{_dhan_icon} Dhan API Token {'(Active)' if _dhan_ok else '(Expired / Missing)'}"):
        st.markdown(
            '<div style="color:#9ca3af;font-size:0.78em;margin-bottom:8px;">'
            'Dhan token expires every 24 hours. Go to '
            '<b>web.dhan.co → Profile → Access Token</b> to get a fresh one.</div>',
            unsafe_allow_html=True,
        )
        new_tok = st.text_area("Paste new access token here:", height=90,
                               key="dhan_new_tok", label_visibility="collapsed",
                               placeholder="eyJhbGciOiJIUzUxMiJ9...")
        if st.button("Update Dhan Token", key="dhan_tok_save", type="primary"):
            tok = new_tok.strip()
            if not tok:
                st.error("Token cannot be empty.")
            else:
                os.environ["DHAN_ACCESS_TOKEN"] = tok
                env_path = "/root/nse-trading-signals/.env"
                try:
                    with open(env_path, "r") as f:
                        lines = f.readlines()
                    new_lines, found = [], False
                    for line in lines:
                        if line.startswith("DHAN_ACCESS_TOKEN="):
                            new_lines.append(f"DHAN_ACCESS_TOKEN={tok}\n")
                            found = True
                        else:
                            new_lines.append(line)
                    if not found:
                        new_lines.append(f"\nDHAN_ACCESS_TOKEN={tok}\n")
                    with open(env_path, "w") as f:
                        f.writelines(new_lines)
                    st.cache_data.clear()
                    st.success("Token updated! Option chain will reload on next refresh.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Saved to env only (file write failed: {e}). Will reset on restart.")
                    st.cache_data.clear()
                    st.rerun()

    st.markdown('<div style="border-bottom:1px solid #2a2a4a;margin:8px 0 12px;"></div>', unsafe_allow_html=True)
    if kite_live:
        try:
            profile = zerodha_api.get_profile()
            margins = zerodha_api.get_margins()
            cash    = (margins.get("equity",{}).get("available",{}).get("cash",0) or
                       margins.get("equity",{}).get("available",{}).get("live_balance",0))
            user_name = profile.get("user_name","--")
            user_id   = profile.get("user_id","--")
        except Exception:
            user_name, user_id, cash = "--","--",0
        st.markdown(f"""
<div style="background:#0d1f0d;border:1px solid #1a3a1a;border-radius:8px;padding:11px;margin-bottom:12px;">
  <div style="color:#4caf50;font-weight:700;font-size:0.88em;margin-bottom:8px;">⚡ ZERODHA CONNECTED</div>
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:5px;">
    <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:5px;padding:6px 8px;">
      <div style="color:#6b7280;font-size:0.52em;text-transform:uppercase;">ACCOUNT</div>
      <div style="color:#e8e8e8;font-weight:600;font-size:0.82em;">{user_name}</div>
      <div style="color:#4b5563;font-size:0.65em;">{user_id}</div>
    </div>
    <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:5px;padding:6px 8px;">
      <div style="color:#6b7280;font-size:0.52em;text-transform:uppercase;">MARGIN</div>
      <div style="color:#4caf50;font-weight:700;">₹{cash:,.0f}</div>
    </div>
    <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:5px;padding:6px 8px;">
      <div style="color:#6b7280;font-size:0.52em;text-transform:uppercase;">DATA</div>
      <div style="color:#7c3aed;font-weight:700;font-size:0.82em;">⚡ REAL-TIME</div>
    </div>
  </div>
</div>""", unsafe_allow_html=True)
        pos_col, ord_col = st.columns(2)
        with pos_col:
            st.markdown('<div style="color:#9ca3af;font-size:0.76em;font-weight:600;margin-bottom:5px;">Positions</div>', unsafe_allow_html=True)
            try:
                positions = zerodha_api.get_positions().get("day",[])
                for p in (positions or [])[:6]:
                    pnl = p.get("pnl",0)
                    clr = "#4caf50" if pnl>=0 else "#ef4444"
                    st.markdown(f'<div style="background:#12121f;border:1px solid #2a2a4a;border-radius:4px;padding:5px 8px;margin-bottom:3px;font-size:0.74em;display:flex;justify-content:space-between;"><span style="color:#e8e8e8;">{p.get("tradingsymbol","")}</span><span style="color:{clr};">{pnl:+,.0f}</span></div>', unsafe_allow_html=True)
                if not positions: st.caption("No positions today")
            except: st.caption("--")
        with ord_col:
            st.markdown('<div style="color:#9ca3af;font-size:0.76em;font-weight:600;margin-bottom:5px;">Orders</div>', unsafe_allow_html=True)
            try:
                orders = zerodha_api.get_orders()
                for o in (orders or [])[-6:]:
                    s = o.get("status","")
                    sc = "#4caf50" if s=="COMPLETE" else ("#ef4444" if s=="REJECTED" else "#f59e0b")
                    st.markdown(f'<div style="background:#12121f;border:1px solid #2a2a4a;border-radius:4px;padding:5px 8px;margin-bottom:3px;font-size:0.74em;display:flex;justify-content:space-between;"><span style="color:#e8e8e8;">{o.get("tradingsymbol","")}</span><span style="color:{sc};">{s}</span></div>', unsafe_allow_html=True)
                if not orders: st.caption("No orders today")
            except: st.caption("--")
        if st.button("Disconnect Zerodha", key="kite_disconnect", type="secondary"):
            zerodha_api._save_token("","")
            st.session_state.kite_restore_attempted = False; st.rerun()
    elif kite_configured:
        login_url = zerodha_api.get_login_url()
        st.markdown(f"""
<div style="background:#12121f;border:1px solid #2a2a4a;border-radius:8px;padding:16px;margin-bottom:12px;text-align:center;">
  <div style="color:#e8e8e8;font-weight:700;margin-bottom:6px;">Zerodha API Keys Detected</div>
  <div style="color:#6b7280;font-size:0.8em;margin-bottom:14px;">Log in once daily. Token expires at midnight IST.</div>
  <a href="{login_url}" target="_blank" style="background:#7c3aed;color:white;padding:9px 24px;border-radius:6px;font-weight:700;font-size:0.88em;text-decoration:none;">Connect Zerodha →</a>
</div>""", unsafe_allow_html=True)
    else:
        st.info("Zerodha not configured. Add KITE_API_KEY and KITE_API_SECRET to Railway/VPS environment variables.")

    st.markdown('<div style="border-bottom:1px solid #2a2a4a;margin-bottom:12px;"></div>', unsafe_allow_html=True)

    subs_list = get_subscribers()
    sms_log   = get_sms_log()
    now_str   = now_ist.strftime("%Y-%m-%d")
    signals_today   = len([e for e in sms_log if e.get("timestamp","")[:10]==now_str])
    delivered_today = len([e for e in sms_log if e.get("timestamp","")[:10]==now_str and e.get("status")=="sent"])
    delivery_rate   = round(delivered_today/signals_today*100) if signals_today else 0
    credits_left    = max(0, 10000 - len(sms_log))

    st.markdown(f"""
<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-bottom:12px;">
  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:9px;">
    <div style="color:#6b7280;font-size:0.52em;text-transform:uppercase;">SUBSCRIBERS</div>
    <div style="color:#e8e8e8;font-size:1.7em;font-weight:700;">{len(subs_list)}</div>
  </div>
  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:9px;">
    <div style="color:#6b7280;font-size:0.52em;text-transform:uppercase;">SENT TODAY</div>
    <div style="color:#e8e8e8;font-size:1.7em;font-weight:700;">{signals_today}</div>
    <div style="color:#6b7280;font-size:0.6em;">{delivery_rate}% delivered</div>
  </div>
  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:9px;">
    <div style="color:#6b7280;font-size:0.52em;text-transform:uppercase;">SMS CREDITS</div>
    <div style="color:#e8e8e8;font-size:1.7em;font-weight:700;">{credits_left:,}</div>
  </div>
  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:9px;">
    <div style="color:#6b7280;font-size:0.52em;text-transform:uppercase;">DELIVERY RATE</div>
    <div style="color:#e8e8e8;font-size:1.7em;font-weight:700;">{delivery_rate}%</div>
  </div>
</div>""", unsafe_allow_html=True)

    sms_left_col, sms_right_col = st.columns([3, 2])

    with sms_left_col:
        st.markdown('<div style="color:#e8e8e8;font-size:0.88em;font-weight:600;margin-bottom:8px;">SUBSCRIBERS</div>', unsafe_allow_html=True)
        sub_filter = st.radio("sub_f", ["All","Active","Inactive"], horizontal=True, key="sub_filter", label_visibility="collapsed")
        search_sub = st.text_input("Search", placeholder="Search by phone or name...", key="search_sub", label_visibility="collapsed")
        add_col1, add_col2, add_col3 = st.columns([3,2,1])
        with add_col1:
            new_phone = st.text_input("Phone", placeholder="+91XXXXXXXXXX", key="new_phone", label_visibility="collapsed")
        with add_col2:
            new_name = st.text_input("Name", placeholder="Name", key="new_name", label_visibility="collapsed")
        with add_col3:
            if st.button("+ Add", key="add_sub_btn", use_container_width=True, type="primary"):
                if new_phone.strip():
                    if add_subscriber(new_phone.strip(), new_name.strip()): st.success("Added!"); st.rerun()
                    else: st.warning("Already exists.")
                else: st.error("Enter phone number.")

        if subs_list:
            filtered = [s for s in subs_list
                        if not search_sub or search_sub.lower() in s.get("phone","").lower()
                        or search_sub.lower() in s.get("name","").lower()]
            tbl_h = '<table style="width:100%;border-collapse:collapse;font-size:0.75em;"><thead><tr style="background:#12121f;">'
            for h in ["NAME","PHONE","STATUS"]:
                tbl_h += f'<th style="padding:5px 7px;color:#4b5563;text-align:left;border-bottom:1px solid #2a2a4a;">{h}</th>'
            tbl_h += '</tr></thead><tbody>'
            for s in filtered[:20]:
                is_active = s.get("active", True)
                if sub_filter=="Active" and not is_active: continue
                if sub_filter=="Inactive" and is_active: continue
                sc = "#4caf50" if is_active else "#ef4444"
                sl = "ACTIVE" if is_active else "PAUSED"
                phone  = s.get("phone","")
                masked = f"+91 {phone[:2]}{'•'*4}{phone[-3:]}" if len(phone)==10 else phone
                tbl_h += f'<tr style="border-bottom:1px solid rgba(42,42,74,0.4);"><td style="padding:5px 7px;color:#e8e8e8;">{s.get("name","-")}</td><td style="padding:5px 7px;color:#9ca3af;">{masked}</td><td style="padding:5px 7px;"><span style="color:{sc};font-size:0.78em;">● {sl}</span></td></tr>'
            tbl_h += '</tbody></table>'
            st.markdown(tbl_h, unsafe_allow_html=True)
            rem_col1, rem_col2 = st.columns([3,1])
            with rem_col1:
                rem_phone = st.text_input("Remove", placeholder="Phone to remove", key="rem_phone", label_visibility="collapsed")
            with rem_col2:
                if st.button("Remove", key="rem_sub_btn", use_container_width=True):
                    if rem_phone.strip():
                        if remove_subscriber(rem_phone.strip()): st.success("Removed."); st.rerun()
                        else: st.warning("Not found.")
        else:
            st.info("No subscribers yet. Add numbers above.")

        st.markdown('<div style="color:#6b7280;font-size:0.58em;text-transform:uppercase;letter-spacing:1px;margin:10px 0 5px;">DELIVERY LOG</div>', unsafe_allow_html=True)
        if sms_log:
            log_tbl = '<table style="width:100%;border-collapse:collapse;font-size:0.73em;"><thead><tr style="background:#12121f;"><th style="padding:5px 6px;color:#4b5563;text-align:left;border-bottom:1px solid #2a2a4a;">TIME</th><th style="padding:5px 6px;color:#4b5563;text-align:left;border-bottom:1px solid #2a2a4a;">SIGNAL</th><th style="padding:5px 6px;color:#4b5563;text-align:center;border-bottom:1px solid #2a2a4a;">STATUS</th></tr></thead><tbody>'
            seen_ts, count = set(), 0
            for entry in reversed(sms_log[-50:]):
                ts_short = entry.get("timestamp","")[:16]
                if ts_short in seen_ts or count >= 6: continue
                seen_ts.add(ts_short); count += 1
                sc = "#4caf50" if entry.get("status")=="sent" else "#ef4444"
                log_tbl += f'<tr style="border-bottom:1px solid rgba(42,42,74,0.3);"><td style="padding:5px 6px;color:#6b7280;">{ts_short[11:]}</td><td style="padding:5px 6px;color:#d1d5db;">{entry.get("message","")[:28]}...</td><td style="padding:5px 6px;text-align:center;color:{sc};font-weight:600;">{entry.get("status","--")}</td></tr>'
            log_tbl += '</tbody></table>'
            st.markdown(log_tbl, unsafe_allow_html=True)
        else:
            st.caption("No SMS sent yet.")

    with sms_right_col:
        st.markdown("""
<div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:12px;">
  <div style="color:#e8e8e8;font-size:0.88em;font-weight:600;margin-bottom:3px;">BROADCAST</div>
  <div style="color:#6b7280;font-size:0.65em;margin-bottom:10px;">Manual signal send to all subscribers.</div>
""", unsafe_allow_html=True)
        templates = {
            "Entry signal": f"🔔 SIGNAL | {'BULLISH' if action=='BUY' else 'BEARISH'}\n{active_sym_key} {_atm_strike(spot_price if data_ok else 0)} {'CE' if action=='BUY' else 'PE'}\nEntry: {spot_price if data_ok else '--'}\nSL: {signal.get('stop_loss') or '--'}\nT1: {signal.get('target') or '--'}\nReply STOP to unsubscribe",
            "Target hit":   f"✅ TARGET HIT\n{active_sym_key}\nBooked profit!\nReply STOP to unsubscribe",
            "Stop loss":    f"⛔ STOP LOSS\n{active_sym_key} SL triggered\nExit immediately.\nReply STOP to unsubscribe",
            "Alert":        f"⚡ MARKET ALERT\n{active_sym_key} unusual activity\nMonitor closely.\nReply STOP to unsubscribe",
        }
        selected_template = st.session_state.get("selected_template","Entry signal")
        tmpl_cols = st.columns(2)
        for i, (label, _) in enumerate(templates.items()):
            with tmpl_cols[i%2]:
                if st.button(label, key=f"tmpl_{label}", use_container_width=True,
                              type="primary" if selected_template==label else "secondary"):
                    st.session_state["selected_template"] = label; st.rerun()

        default_msg = templates.get(selected_template,"")
        bc_message = st.text_area("Message", value=default_msg, height=120, key="bc_message", label_visibility="collapsed")
        st.markdown(f'<div style="text-align:right;color:#4b5563;font-size:0.62em;">{len(bc_message)}/160</div>', unsafe_allow_html=True)

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
                    "option_type": "CE" if action=="BUY" else "PE",
                    "expiry": "Weekly", "entry_price": spot_val,
                    "target_price": signal.get("target") or round(spot_val*1.01,2),
                    "stop_loss": signal.get("stop_loss") or round(spot_val*0.997,2),
                    "quantity": 1,
                }
                results = send_sms_to_all(test_trade, action="BUY")
                sent = sum(1 for r in results if r.get("status")=="sent")
                fail = sum(1 for r in results if r.get("status")=="failed")
                if sent > 0: st.success(f"✓ Sent to {sent} subscriber(s)")
                elif fail > 0: st.error(f"Failed ({fail}): check Fast2SMS API key")
                else: st.info("No active subscribers.")
        st.markdown('</div>', unsafe_allow_html=True)
        st.caption("Educational use only — not buy/sell recommendations.")


st.markdown(
    f'<div style="border-top:1px solid #2a2a4a;margin-top:10px;padding:6px 4px;color:#4b5563;font-size:0.62em;">'
    f'For educational purposes only. Not financial advice. '
    f'Auto-refreshes every {"15s" if mkt_open else "5min"}.'
    f'</div>',
    unsafe_allow_html=True,
)
