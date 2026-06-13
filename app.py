import streamlit as st
from streamlit_autorefresh import st_autorefresh
from datetime import datetime
import pytz
import concurrent.futures
import pandas as pd
import os
import urllib.parse

# Load .env file directly — bypasses systemd EnvironmentFile parsing quirks
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _ef:
        for _line in _ef:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

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

IST = pytz.timezone("Asia/Kolkata")
_TV_INT = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "1h": "60", "1D": "D"}

SYMBOL_ALIASES = {
    "NIFTY": "NIFTY 50", "NIFTY50": "NIFTY 50",
    "BANKNIFTY": "BANK NIFTY", "INFY": "INFOSYS",
    "HDFCBANK": "HDFC BANK", "ICICIBANK": "ICICI BANK",
    "MM": "M&M", "BAJAJAUTO": "BAJAJ-AUTO",
}

# NSE F&O stocks grouped by sector (trading symbols)
SECTOR_STOCKS = {
    "Banking 🏦":          ["HDFCBANK","ICICIBANK","SBIN","KOTAKBANK","AXISBANK","INDUSINDBK","BANKBARODA","PNB","CANBK","FEDERALBNK","IDFCFIRSTB","BANDHANBNK"],
    "IT / Tech 💻":        ["TCS","INFY","WIPRO","HCLTECH","TECHM","LTIM","MPHASIS","PERSISTENT","COFORGE","OFSS"],
    "Auto 🚗":             ["TATAMOTORS","MARUTI","M&M","BAJAJ-AUTO","HEROMOTOCO","EICHERMOT","TVSMOTOR","ASHOKLEY","MOTHERSON","BALKRISIND"],
    "Pharma 💊":           ["SUNPHARMA","DRREDDY","CIPLA","DIVISLAB","AUROPHARMA","TORNTPHARM","LUPIN","ALKEM","BIOCON","IPCALAB"],
    "FMCG 🛒":             ["HINDUNILVR","ITC","NESTLEIND","BRITANNIA","MARICO","DABUR","GODREJCP","COLPAL","TATACONSUM","EMAMILTD"],
    "Metal & Mining ⛏":   ["TATASTEEL","HINDALCO","JSWSTEEL","SAIL","VEDL","NMDC","NATIONALUM","HINDCOPPER","APLAPOLLO"],
    "Energy & Oil ⚡":     ["RELIANCE","ONGC","BPCL","IOC","GAIL","PETRONET","MGL","IGL","TATAPOWER","ADANIGREEN"],
    "Infrastructure 🏗":   ["LT","ULTRACEMCO","GRASIM","SHREECEM","ADANIPORTS","RVNL","IRFC","PFC","RECLTD","NTPC"],
    "Telecom 📡":          ["BHARTIARTL","IDEA","INDUSTOWER"],
    "Consumer & Retail 🛍":["ZOMATO","DMART","TRENT","JUBLFOOD","DEVYANI","SAPPHIRE","NYKAA","INDHOTEL","EIHOTEL","LEMONTRE"],
    "Financial Services 📈":["BAJFINANCE","BAJAJFINSV","HDFCAMC","MUTHOOTFIN","CHOLAFIN","SBICARD","MANAPPURAM","IIFL","M&MFIN"],
}
# Flat deduplicated list of all stocks across every sector (used by Scanner)
_SECTOR_UNIVERSE = tuple(sorted({s for stocks in SECTOR_STOCKS.values() for s in stocks}))

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

# Watchlist click handlers
if _qp.get("wl_select"):
    _sel_sym = urllib.parse.unquote_plus(_qp["wl_select"])
    add_to_watchlist(_sel_sym)
    st.session_state.active_symbol = _sel_sym
    st.session_state["wl_search"] = ""
    st.query_params.clear()
    st.rerun()
if _qp.get("wl_delete"):
    from sms_sender import remove_from_watchlist as _rm_wl
    _rm_wl(urllib.parse.unquote_plus(_qp["wl_delete"]))
    st.query_params.clear()
    st.rerun()

kite_configured = bool(os.environ.get("KITE_API_KEY","").strip() and os.environ.get("KITE_API_SECRET","").strip())
kite_live = zerodha_api.is_connected() if kite_configured else False

_refresh_ms = 60_000 if (is_market_open() and kite_live) else (60_000 if is_market_open() else 300_000)
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
for _k, _v in [("active_symbol","NIFTY 50"), ("chart_tf","5m"), ("_wl_selected",None), ("navigate_to_tab",None)]:
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

_STRIKE_STEP = {
    "NIFTY 50": 50, "BANK NIFTY": 100, "FIN NIFTY": 50,
    "MIDCAP SELECT": 25, "SENSEX": 100,
}

def _opt_strike(price: float, sym_key: str) -> int:
    """Return nearest ATM option strike using NSE-standard intervals."""
    if price <= 0: return 0
    step = _STRIKE_STEP.get(sym_key)
    if not step:
        # NSE F&O stock strike intervals by price band
        step = (1   if price < 25  else
                2.5 if price < 50  else
                5   if price < 250 else
                10  if price < 1000 else
                50  if price < 5000 else
                100)
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


def compute_pivots(df, timeframe: str = "5m") -> dict:
    """Standard pivot points from previous session OHLC."""
    if df is None or df.empty:
        return {}
    try:
        if timeframe == "1D":
            if len(df) < 2:
                return {}
            prev = df.iloc[-2]
            H, L, C = float(prev["High"]), float(prev["Low"]), float(prev["Close"])
        else:
            df2 = df.copy()
            df2["_d"] = pd.to_datetime(df2.index).date
            today = df2["_d"].iloc[-1]
            prev_df = df2[df2["_d"] < today]
            if prev_df.empty:
                H = float(df["High"].max())
                L = float(df["Low"].min())
                C = float(df["Close"].iloc[-1])
            else:
                ld = prev_df["_d"].iloc[-1]
                day = prev_df[prev_df["_d"] == ld]
                H, L, C = float(day["High"].max()), float(day["Low"].min()), float(day["Close"].iloc[-1])
        PP = (H + L + C) / 3
        rng = H - L
        return {
            "PP": round(PP, 2),
            "R1": round(2 * PP - L, 2),
            "R2": round(PP + rng, 2),
            "S1": round(2 * PP - H, 2),
            "S2": round(PP - rng, 2),
        }
    except Exception:
        return {}

def _df_to_lc_candles(df, timeframe: str) -> list:
    """Convert yfinance OHLC DataFrame to TradingView Lightweight Charts format."""
    rows = []
    for ts, row in df.iterrows():
        try:
            if timeframe == "1D":
                t = ts.date().isoformat() if hasattr(ts, "date") else str(ts)[:10]
            else:
                _utc = int(ts.timestamp()) if hasattr(ts, "timestamp") else int(pd.Timestamp(ts).timestamp())
                t = _utc + 19800  # shift UTC → IST (+5:30) for chart display
            rows.append({
                "time": t,
                "open":  round(float(row["Open"]),  2),
                "high":  round(float(row["High"]),  2),
                "low":   round(float(row["Low"]),   2),
                "close": round(float(row["Close"]), 2),
            })
        except Exception:
            continue
    return rows

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

@st.cache_data(ttl=90 if _mkt_open_now else 300)
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

@st.cache_data(ttl=60 if _mkt_open_now else 600)
def _load_wl_changes(symbols_tuple):
    """Fetch day % change for watchlist symbols via yfinance fast_info."""
    results = {}
    def _f(name):
        sym = SYMBOLS.get(name, _make_sym(name))
        try:
            import yfinance as yf
            fi = yf.Ticker(sym["yf"]).fast_info
            raw = getattr(fi, "regularMarketChangePercent", None)
            if raw is not None:
                return name, round(float(raw), 2)
        except Exception:
            pass
        return name, None
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_f, n): n for n in symbols_tuple}
        try:
            for fut in concurrent.futures.as_completed(futs, timeout=12):
                try:
                    n, pct = fut.result()
                    results[n] = pct
                except Exception:
                    pass
        except concurrent.futures.TimeoutError:
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
    period, interval = {"1m":("5d","1m"),"3m":("5d","2m"),"5m":("5d","5m"),
                        "15m":("5d","15m"),"1h":("5d","60m"),"1D":("1mo","1d")}.get(timeframe, ("5d","5m"))
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

@st.cache_data(ttl=120 if _mkt_open_now else 3600)
def _load_scanner_signals(symbols_tuple: tuple, timeframe: str = "5m", use_kite: bool = False) -> dict:
    """
    Compute RSI+MACD+Supertrend+VWAP signals for all listed F&O symbols.
    Uses Kite historical data when use_kite=True, yfinance otherwise.
    """
    _tf_map = {
        "1m":("1d","1m"), "3m":("1d","2m"), "5m":("1d","5m"),
        "15m":("5d","15m"), "1h":("5d","60m"), "1D":("1mo","1d"),
    }
    period, interval = _tf_map.get(timeframe, ("1d","5m"))

    if use_kite and zerodha_api.is_connected():
        ohlcv_map = zerodha_api.get_historical_data_bulk(list(symbols_tuple), timeframe, max_workers=5)
    else:
        # yfinance bulk fallback when Kite is offline
        import yfinance as yf
        _tickers = " ".join(f"{s}.NS" for s in symbols_tuple)
        try:
            _dl = yf.download(_tickers, period=period, interval=interval,
                              group_by="ticker", threads=True, progress=False, auto_adjust=True)
            ohlcv_map = {}
            for _s in symbols_tuple:
                try:
                    _df = _dl[f"{_s}.NS"].dropna() if f"{_s}.NS" in _dl.columns.get_level_values(0) else pd.DataFrame()
                    if not _df.empty:
                        ohlcv_map[_s] = _df
                except Exception:
                    pass
        except Exception:
            ohlcv_map = {}

    def _one(sym_key):
        df = ohlcv_map.get(sym_key)
        if df is None or df.empty or len(df) < 14:
            return sym_key, None
        try:
            spot = float(df["Close"].iloc[-1])
            rsi_d  = compute_rsi(df)
            macd_d = compute_macd(df)
            st_d   = compute_supertrend(df)
            vwap_d = compute_vwap(df)
            sig    = generate_signal(rsi_d, macd_d, st_d, vwap_d, None, spot)
            return sym_key, {
                "spot":       round(spot, 2),
                "rsi":        round(float(rsi_d.get("value") or 50), 1) if rsi_d else 50.0,
                "macd":       (macd_d.get("signal") or "--") if macd_d else "--",
                "supertrend": "BULL" if (st_d and st_d.get("direction") == 1) else "BEAR",
                "vwap":       (vwap_d.get("signal") or "--") if vwap_d else "--",
                "signal":     sig.get("action", "HOLD"),
                "buy_count":  sig.get("buy_count", 0),
                "sell_count": sig.get("sell_count", 0),
            }
        except Exception:
            return sym_key, None

    # Compute indicators for all Kite-fetched symbols in parallel (CPU-only, fast)
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        futs = {ex.submit(_one, k): k for k in symbols_tuple}
        try:
            for fut in concurrent.futures.as_completed(futs, timeout=60):
                try:
                    k, v = fut.result()
                    if v: results[k] = v
                except Exception:
                    pass
        except concurrent.futures.TimeoutError:
            pass
    return results

@st.cache_data(ttl=3600)
def _load_kite_fo_symbols() -> tuple:
    """Fetch full F&O underlying symbol list from Kite NFO instruments (cached 1h)."""
    try:
        syms = zerodha_api.get_fo_underlying_symbols()
        # Filter out non-equity indices that don't have yfinance data
        _skip = {"FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX50"}
        return tuple(sorted(s for s in syms if s not in _skip))
    except Exception:
        return ()

@st.cache_data(ttl=120 if _mkt_open_now else 3600)
def _load_sector_signals(nse_symbols_tuple: tuple, timeframe: str = "15m", use_kite: bool = False) -> dict:
    """
    Score each stock in a sector 0-5 for BUY/SELL conviction using
    RSI + MACD + Supertrend + VWAP + Volume spike.
    Uses Kite historical data when use_kite=True, yfinance otherwise.
    """
    _tf_map = {"5m":("1d","5m"), "15m":("5d","15m"), "1h":("5d","60m"), "1D":("1mo","1d")}
    period, interval = _tf_map.get(timeframe, ("5d","15m"))

    if use_kite and zerodha_api.is_connected():
        ohlcv_map = zerodha_api.get_historical_data_bulk(list(nse_symbols_tuple), timeframe, max_workers=5)
    else:
        # yfinance bulk fallback when Kite is offline
        import yfinance as yf
        _tickers = " ".join(f"{s}.NS" for s in nse_symbols_tuple)
        try:
            _dl = yf.download(_tickers, period=period, interval=interval,
                              group_by="ticker", threads=True, progress=False, auto_adjust=True)
            ohlcv_map = {}
            for _s in nse_symbols_tuple:
                try:
                    _df = _dl[f"{_s}.NS"].dropna() if f"{_s}.NS" in _dl.columns.get_level_values(0) else pd.DataFrame()
                    if not _df.empty:
                        ohlcv_map[_s] = _df
                except Exception:
                    pass
        except Exception:
            ohlcv_map = {}

    def _one(nse_sym):
        try:
            df = ohlcv_map.get(nse_sym)
            if df is None or df.empty or len(df) < 20:
                return nse_sym, None
            spot = float(df["Close"].iloc[-1])
            rsi_d  = compute_rsi(df)
            macd_d = compute_macd(df)
            st_d   = compute_supertrend(df)
            vwap_d = compute_vwap(df)

            buy_pts = sell_pts = 0
            rsi_sig  = (rsi_d.get("signal")  or "NEUTRAL") if rsi_d  else "NEUTRAL"
            macd_sig = (macd_d.get("signal") or "NEUTRAL") if macd_d else "NEUTRAL"
            vwap_sig = (vwap_d.get("signal") or "NEUTRAL") if vwap_d else "NEUTRAL"
            if rsi_sig  == "BUY":  buy_pts  += 1
            elif rsi_sig  == "SELL": sell_pts += 1
            if macd_sig == "BUY":  buy_pts  += 1
            elif macd_sig == "SELL": sell_pts += 1
            if st_d:
                if st_d.get("direction") == 1: buy_pts  += 1
                else:                           sell_pts += 1
            if vwap_sig == "BUY":  buy_pts  += 1
            elif vwap_sig == "SELL": sell_pts += 1
            try:
                avg_vol   = float(df["Volume"].iloc[:-1].tail(20).mean())
                cur_vol   = float(df["Volume"].iloc[-1])
                vol_spike = avg_vol > 0 and cur_vol > avg_vol * 1.5
            except Exception:
                vol_spike = False
            if vol_spike:
                if buy_pts > sell_pts:   buy_pts  += 1
                elif sell_pts > buy_pts: sell_pts += 1

            max_score = max(buy_pts, sell_pts)
            direction = "BUY" if buy_pts > sell_pts else ("SELL" if sell_pts > buy_pts else "NEUTRAL")
            try:
                day_pct = round((df["Close"].iloc[-1] - df["Open"].iloc[0]) / df["Open"].iloc[0] * 100, 2)
            except Exception:
                day_pct = 0.0
            rsi_val = round(float(rsi_d.get("value") or 50), 1) if rsi_d else 50.0
            return nse_sym, {
                "spot": round(spot, 2),
                "buy_pts": buy_pts, "sell_pts": sell_pts,
                "score": max_score, "direction": direction,
                "rsi": rsi_val, "macd": macd_sig,
                "supertrend": "BULL" if (st_d and st_d.get("direction") == 1) else "BEAR",
                "vwap": vwap_sig, "vol_spike": vol_spike, "day_pct": day_pct,
            }
        except Exception:
            return nse_sym, None

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(_one, s): s for s in nse_symbols_tuple}
        try:
            for fut in concurrent.futures.as_completed(futs, timeout=50):
                try:
                    s, v = fut.result()
                    if v: results[s] = v
                except Exception:
                    pass
        except concurrent.futures.TimeoutError:
            pass
    return results

# Kite uses different instrument names for indices
_KITE_INDEX_INST = {
    "NIFTY 50":       "NIFTY 50",
    "BANK NIFTY":     "NIFTY BANK",
    "FIN NIFTY":      "NIFTY FIN SERVICE",
    "MIDCAP SELECT":  "NIFTY MID SELECT",
    "INDIA VIX":      "INDIA VIX",
}

def _kite_nse_sym(sym_key: str, sym: dict) -> str:
    """Return the NSE symbol string to pass to zerodha_api.get_quotes()."""
    if sym_key in _KITE_INDEX_INST:
        return _KITE_INDEX_INST[sym_key]
    nse = sym.get("nse", "")
    return nse if nse and not sym.get("yf","").startswith(("CL=","NG=","GC=","SI=")) else ""

@st.cache_data(ttl=30 if _mkt_open_now else 300)
def _load_kite_quotes(symbols_tuple: tuple) -> dict:
    """
    Batch real-time quotes from Kite Connect for all given symbol keys.
    Returns {sym_key: {"ltp": float, "pct": float, "change": float}}.
    One API call for all symbols — sub-second latency.
    """
    nse_syms, key_map = [], {}
    for k in symbols_tuple:
        sym = SYMBOLS.get(k, _make_sym(k))
        nse = _kite_nse_sym(k, sym)
        if nse:
            nse_syms.append(nse)
            key_map[nse] = k
    if not nse_syms:
        return {}
    try:
        raw = zerodha_api.get_quotes(nse_syms)
        result = {}
        for nse, data in raw.items():
            k = key_map.get(nse, nse)
            result[k] = {"ltp": data["last_price"], "pct": data["pct"], "change": data["change"]}
        return result
    except Exception:
        return {}

@st.cache_data(ttl=30 if _mkt_open_now else 300)
def _load_kite_chart(nse_sym: str, timeframe: str) -> pd.DataFrame:
    """Fetch real-time OHLCV candles from Kite Connect. Returns empty DataFrame on failure."""
    if not nse_sym:
        return pd.DataFrame()
    try:
        df = zerodha_api.get_historical_data(nse_sym, timeframe)
        return df if (df is not None and not df.empty) else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


# ── Resolve active symbol ──
if st.session_state._wl_selected:
    st.session_state.active_symbol = st.session_state._wl_selected
    st.session_state._wl_selected = None

active_sym_key = st.session_state.active_symbol
active_sym = SYMBOLS.get(active_sym_key, _make_sym(active_sym_key))

# ── Market state (used throughout) ──
indices_data = {} if kite_live else _load_indices()
now_ist = datetime.now(IST)
mkt_open = is_market_open()
mkt_color = "#4caf50" if mkt_open else "#ef4444"
mkt_text  = "LIVE" if mkt_open else "CLOSED"

# ── Watchlist + live Kite quotes (fetched once, used in both columns) ──
saved_watchlist = get_watchlist()
if not saved_watchlist:
    for _d in ["NIFTY 50","BANK NIFTY","FIN NIFTY","MIDCAP SELECT","MCX CRUDE OIL","RELIANCE","HDFC BANK","TCS","INFOSYS"]:
        add_to_watchlist(_d)
    saved_watchlist = get_watchlist()

# All symbols to quote: watchlist + active (in case active isn't in watchlist)
_quote_set = tuple(sorted(set(saved_watchlist) | {active_sym_key}))
kite_quotes = _load_kite_quotes(_quote_set) if kite_live else {}

if kite_live:
    # Kite quotes already fetched above — use them directly, skip yfinance entirely
    wl_prices  = {k: v["ltp"]  for k, v in kite_quotes.items() if v.get("ltp")}
    wl_changes = {k: v["pct"]  for k, v in kite_quotes.items() if v.get("pct") is not None}
else:
    wl_prices  = _load_wl_prices(tuple(saved_watchlist)) if saved_watchlist else {}
    wl_changes = _load_wl_changes(tuple(saved_watchlist)) if saved_watchlist else {}

# Index % changes from indices_data when Kite not connected
_idx_pct_keys = {
    "NIFTY 50": "NIFTY 50", "BANK NIFTY": "BANK NIFTY",
    "FIN NIFTY": "FIN NIFTY", "MIDCAP SELECT": "MIDCAP SELECT", "INDIA VIX": "INDIA VIX",
}
for _ik, _iv in _idx_pct_keys.items():
    if not kite_live and _iv in indices_data and indices_data[_iv].get("pct") is not None:
        wl_changes[_ik] = indices_data[_iv]["pct"]


# ═══════════════════════════════════════════════
#  3-COLUMN LAYOUT: Left | Center | Right
# ═══════════════════════════════════════════════
left_col, main_col = st.columns([5, 20])


# ══════════════════════════════════════════════
#  LEFT: Watchlist
# ══════════════════════════════════════════════
with left_col:
    st.markdown(f"""
<div style="padding:8px 10px 6px;border-bottom:1px solid #2a2a4a;background:#141428;">
  <span style="color:#e8e8e8;font-size:0.9em;font-weight:700;">Options Terminal</span>
  <span style="margin-left:8px;background:{mkt_color}22;color:{mkt_color};
               padding:1px 7px;border-radius:10px;font-size:0.55em;font-weight:700;">
    ● {mkt_text}
  </span>
</div>""", unsafe_allow_html=True)

    # Search bar (always visible at top)
    sym_search = st.text_input(
        "Search", placeholder="🔍  Search eg. NIFTY, RELIANCE...",
        key="wl_search", label_visibility="collapsed",
    )
    if sym_search.strip():
        candidates = _find_symbol_candidates(sym_search.strip())
        if candidates:
            import html as _html_s
            _sr = '<div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;overflow:hidden;margin:2px 0 4px;">'
            for _c in candidates[:7]:
                _fn = _html_s.escape(SYMBOL_SHORT.get(_c, ("", _c))[1] or _c)
                _tk = SYMBOL_SHORT.get(_c, (_c,))[0]
                _href = "?wl_select=" + urllib.parse.quote_plus(_c)
                _is_act = _c == active_sym_key
                _bg = "background:rgba(56,126,209,0.08);" if _is_act else ""
                _sr += (
                    f'<a href="{_href}" style="{_bg}display:flex;justify-content:space-between;'
                    f'align-items:center;padding:9px 12px;border-bottom:1px solid rgba(42,42,74,0.3);'
                    f'text-decoration:none;">'
                    f'<div><span style="display:block;color:#e8e8e8;font-size:0.82em;font-weight:600;">{_fn}</span>'
                    f'<span style="color:#4b5563;font-size:0.57em;">NSE · {_tk}</span></div>'
                    f'<span style="color:#387ed1;font-size:0.8em;">+</span>'
                    f'</a>'
                )
            _sr += '</div>'
            st.markdown(_sr, unsafe_allow_html=True)
        else:
            st.markdown('<div style="color:#4b5563;font-size:0.72em;padding:3px 2px;">No results found.</div>', unsafe_allow_html=True)

    # saved_watchlist, wl_prices, wl_changes already computed above (before columns)
    st.markdown('<div style="padding:4px 10px 3px;border-bottom:1px solid #1e1e2e;">'
                '<span style="color:#374151;font-size:0.52em;text-transform:uppercase;letter-spacing:1px;">WATCHLIST</span>'
                '</div>', unsafe_allow_html=True)

    import json as _wl_json
    import html as _html
    # Build symbol metadata for JS
    _wl_syms_js = []
    for _wn in saved_watchlist:
        _yf = SYMBOLS.get(_wn, {}).get("yf", "")
        _exch = "MCX" if _yf.startswith(("CL=","NG=","GC=","SI=")) else ("BSE" if _yf.startswith("^BSE") else "NSE")
        _wl_syms_js.append({
            "key":  _wn,
            "name": SYMBOL_SHORT.get(_wn, ("", _wn))[1] or _wn,
            "exch": _exch,
        })
    _wl_syms_json  = _wl_json.dumps(_wl_syms_js)
    _wl_init_json  = _wl_json.dumps({k: {"price": v["ltp"], "pct": v["pct"], "change": v.get("change", 0)}
                                      for k, v in kite_quotes.items() if v.get("ltp")})
    _wl_active_js  = active_sym_key.replace("'", "\\'")
    _wl_row_h      = max(len(saved_watchlist) * 46 + 4, 100)

    import streamlit.components.v1 as _wl_comp
    _wl_comp.html(f"""<!DOCTYPE html><html><head>
<style>
*{{margin:0;padding:0;box-sizing:border-box;font-family:'Inter',sans-serif;}}
body{{background:#0e0e1a;overflow-x:hidden;}}
.row{{display:flex;border-bottom:1px solid rgba(42,42,74,0.35);cursor:pointer;border-left:3px solid transparent;}}
.row:hover{{background:rgba(56,126,209,0.04);}}
.row.active{{border-left-color:#387ed1;background:rgba(56,126,209,0.07);}}
.main{{flex:1;display:flex;justify-content:space-between;align-items:center;padding:10px 8px 10px 11px;}}
.nm{{color:#e8e8e8;font-size:0.82em;font-weight:600;display:block;}}
.row.active .nm{{color:#60a5fa;}}
.ex{{color:#4b5563;font-size:0.57em;}}
.pr{{text-align:right;}}
.ltp{{font-size:0.82em;font-weight:700;}}
.sub{{font-size:0.6em;}}
.del{{color:#2d3748;font-size:0.8em;padding:0 8px;display:flex;align-items:center;}}
.del:hover{{color:#ef4444;}}
</style></head><body>
<div id="wl"></div>
<script>
const WL     = {_wl_syms_json};
const ACTIVE = '{_wl_active_js}';
let prices   = {_wl_init_json};

function fmtN(n){{
  if(n>=100000) return (n/100000).toFixed(2)+'L';
  if(n>=1000)   return n.toLocaleString('en-IN',{{minimumFractionDigits:2,maximumFractionDigits:2}});
  return n.toFixed(2);
}}
function nav(url){{ window.parent.location.href = url; }}

function render(){{
  const wl = document.getElementById('wl');
  wl.innerHTML = '';
  WL.forEach(s=>{{
    const isAct = s.key === ACTIVE;
    const d = prices[s.key];
    let ltpHtml='<span class="ltp" style="color:#9ca3af">--</span>', subHtml='';
    if(d && d.price>0){{
      const clr = d.pct>=0?'#4caf50':'#ef4444';
      const arr = d.pct>=0?'▲':'▼';
      const acv = Math.abs(d.change||0);
      const sgn = d.pct>=0?'+':'-';
      ltpHtml = `<span class="ltp" style="color:${{clr}}">${{fmtN(d.price)}} ${{arr}}</span>`;
      subHtml = `<span class="sub" style="color:${{clr}}">${{sgn}}${{fmtN(acv)}} (${{Math.abs(d.pct).toFixed(2)}}%)</span>`;
    }}
    const enc = encodeURIComponent(s.key);
    const row = document.createElement('div');
    row.className='row'+(isAct?' active':'');
    row.innerHTML=`
      <div class="main" onclick="nav('?wl_select=${{enc}}')">
        <div><span class="nm">${{s.name}}</span><span class="ex">${{s.exch}}</span></div>
        <div class="pr">${{ltpHtml}}<br>${{subHtml}}</div>
      </div>
      <span class="del" onclick="nav('?wl_delete=${{enc}}')">&#x2715;</span>`;
    wl.appendChild(row);
  }});
}}

render();

async function poll(){{
  const keys = WL.map(s=>s.key).join(',');
  try{{
    const r = await fetch('/api/live/watchlist?keys='+encodeURIComponent(keys));
    if(r.ok){{ prices = await r.json(); render(); }}
  }}catch(e){{}}
}}
poll();
setInterval(poll, 2000);
</script></body></html>""", height=_wl_row_h, scrolling=False)

    # Manual add / remove
    wl_input = st.text_input("Add", placeholder="+ IDEA  or  - COFORGE", key="wl_input", label_visibility="collapsed")
    if wl_input.strip():
        inp = wl_input.strip()
        if inp.startswith("-"):
            remove_from_watchlist(inp.lstrip("- ").upper()); st.rerun()
        else:
            sym_to_add = inp.lstrip("+ ").upper()
            candidates = _find_symbol_candidates(sym_to_add)
            add_to_watchlist(candidates[0] if candidates else sym_to_add); st.rerun()


with main_col:
    _chart_tab, _oc_tab, _scan_tab, _picks_tab = st.tabs(["📈  Chart", "⛓  Option Chain", "📊  Scanner", "🎯  Sector Picks"])
    # Programmatic tab navigation (triggered from Sector Picks buttons)
    _nav_to = st.session_state.get("navigate_to_tab")
    if _nav_to is not None:
        st.session_state.navigate_to_tab = None
        import streamlit.components.v1 as _components
        _components.html(f"""<script>
        (function(){{
            function _clickTab(){{
                var lists = window.parent.document.querySelectorAll('[data-baseweb="tab-list"]');
                if (!lists.length){{ setTimeout(_clickTab, 100); return; }}
                var btns = lists[0].querySelectorAll('button[role="tab"]');
                if (btns[{_nav_to}]) btns[{_nav_to}].click();
            }}
            setTimeout(_clickTab, 150);
        }})();
        </script>""", height=0)

@st.cache_data(ttl=30 if _mkt_open_now else 300)
def _load_chart_and_indicators(sym_key: str, nse_sym: str, yf_sym: str, timeframe: str):
    """
    Single cached call per (symbol, timeframe) — fetches OHLCV + computes all
    indicators in one shot. Cache hit returns instantly (< 1 ms).
    Cache miss triggers Kite API + ta-lib computations (~1-3 s, happens once per 30 s).
    """
    import yfinance as _yf
    df = pd.DataFrame()
    spot = None

    # 1. Kite historical data (fast, authoritative)
    if nse_sym and zerodha_api.is_connected():
        try:
            df = zerodha_api.get_historical_data(nse_sym, timeframe)
            if df is not None and not df.empty:
                spot = float(df["Close"].iloc[-1])
        except Exception:
            pass

    # 2. yfinance fallback
    if (df is None or df.empty) and yf_sym:
        _period, _iv = {"1m":("5d","1m"),"3m":("5d","2m"),"5m":("5d","5m"),
                        "15m":("5d","15m"),"1h":("5d","60m"),"1D":("1mo","1d")}.get(timeframe, ("5d","5m"))
        try:
            _tmp = _yf.Ticker(yf_sym).history(period=_period, interval=_iv)
            if _tmp is not None and not _tmp.empty:
                df, spot = _tmp, float(_tmp["Close"].iloc[-1])
        except Exception:
            pass

    data_ok = spot is not None and df is not None and not df.empty

    rsi_d = macd_d = st_d = vwap_d = None
    all_signals, pivots = [], {}
    signal = {"action":"HOLD","buy_count":0,"sell_count":0,"target":None,"stop_loss":None}

    if data_ok:
        try:
            rsi_d  = compute_rsi(df)
            macd_d = compute_macd(df)
            st_d   = compute_supertrend(df)
            vwap_d = compute_vwap(df)
            signal = generate_signal(rsi_d, macd_d, st_d, vwap_d, evaluate_oi(None), spot)
            all_signals = compute_all_signals(df, timeframe)
            pivots = compute_pivots(df, timeframe)
        except Exception:
            pass

    return spot, df if df is not None else pd.DataFrame(), rsi_d, macd_d, st_d, vwap_d, signal, all_signals, pivots


@st.cache_data(ttl=120 if _mkt_open_now else 600)
def _get_option_rec_cached(nse_sym: str, atm_strike: int, action: str):
    """Cache option recommendation — avoids NSE API call on every page load."""
    try:
        return get_option_recommendation(nse_sym, float(atm_strike), action)
    except Exception:
        return None


# ══════════════════════════════════════════════
#  CHART TAB
# ══════════════════════════════════════════════
with _chart_tab:
    # Single cached call — returns instantly on warm cache
    _chart_nse = active_sym.get("nse","")
    _chart_yf  = active_sym.get("yf","")
    _spot_cached, df, rsi_d, macd_d, st_d, vwap_d, signal, all_signals, pivots = \
        _load_chart_and_indicators(active_sym_key, _chart_nse, _chart_yf, st.session_state.chart_tf)

    # Always use the freshest Kite LTP when connected (kite_quotes already fetched above)
    spot_price = (kite_quotes.get(active_sym_key, {}).get("ltp") or _spot_cached) if kite_live else _spot_cached

    data_ok = (spot_price is not None) and (df is not None) and (not df.empty)

    action = signal.get("action", "HOLD")
    option_rec = None
    if data_ok and action in ("BUY","SELL") and _chart_nse:
        _atm_key = _opt_strike(spot_price, active_sym_key)
        option_rec = _get_option_rec_cached(_chart_nse, _atm_key, action)

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

    # ── Symbol header + Signal box (always visible) ──
    pivots = compute_pivots(df, st.session_state.chart_tf) if data_ok else {}
    if data_ok:
        day_chg = df["Close"].iloc[-1] - df["Open"].iloc[0]
        day_pct = (day_chg / df["Open"].iloc[0]) * 100
        chg_c = _pct_color(day_pct)
        arrow  = "▲" if day_chg >= 0 else "▼"
        disp_short = SYMBOL_SHORT.get(active_sym_key, (active_sym_key,))[0]
        # Use NSE symbol for option contract name (e.g. HDFCBANK, not "HDFC BANK")
        _nse_label = active_sym.get("nse") or disp_short
        # Only show CE/PE for F&O-eligible symbols (nse field non-empty, not commodity)
        _has_fo = bool(active_sym.get("nse") and not active_sym.get("yf","").startswith(("CL=","NG=","GC=","SI=","^BSESN")))

        # Signal box config
        _atm = _opt_strike(spot_price, active_sym_key)
        if action == "BUY":
            _t1, _t2 = pivots.get("R1", 0), pivots.get("R2", 0)
            _sl1, _sl2 = pivots.get("PP", 0), pivots.get("S1", 0)
            _sig_bg = "linear-gradient(135deg,#0a1f0a 0%,#0d1a0d 100%)"
            _sig_border, _sig_accent = "#1e4d1e", "#4caf50"
            _sig_arrow, _sig_label = "▲", "BUY"
            if _has_fo:
                _opt_str = option_rec.get("strike", _atm) if option_rec else _atm
                _opt_ltp = option_rec.get("ltp", 0) if option_rec else 0
                _opt_tgt = option_rec.get("premium_target", 0) if option_rec else 0
                _opt_sl  = option_rec.get("premium_sl", 0) if option_rec else 0
                _opt_avg = round((_opt_ltp + _opt_tgt) / 2, 0) if _opt_ltp and _opt_tgt else 0
                if _opt_ltp:
                    _sig_msg = (
                        f'BUY <b>{_nse_label} {int(_opt_str):,} CE</b>'
                        f' &nbsp;@ <b style="color:#4caf50;font-size:1.05em;">₹{_opt_ltp:.0f}</b>'
                        f' &nbsp;·&nbsp; <span style="color:#fbbf24;">Target ₹{_opt_tgt:.0f}</span>'
                        f' &nbsp;·&nbsp; <span style="color:#fb923c;">Avg ₹{_opt_avg:.0f}</span>'
                        f' &nbsp;·&nbsp; <span style="color:#ef4444;">SL ₹{_opt_sl:.0f}</span>'
                    )
                else:
                    _sig_msg = (
                        f'BUY <b>{_nse_label} {_atm:,} CE</b>'
                        f' &nbsp;<span style="color:#6b7280;font-size:0.85em;">@ ₹{spot_price:,.0f} · ATM Call</span>'
                    )
            else:
                _sig_msg = f'Buy <b>{disp_short}</b> @ ₹{spot_price:,.0f}'
        elif action == "SELL":
            _t1, _t2 = pivots.get("S1", 0), pivots.get("S2", 0)
            _sl1, _sl2 = pivots.get("PP", 0), pivots.get("R1", 0)
            _sig_bg = "linear-gradient(135deg,#1f0a0a 0%,#1a0d0d 100%)"
            _sig_border, _sig_accent = "#4d1e1e", "#ef4444"
            _sig_arrow, _sig_label = "▼", "SELL"
            if _has_fo:
                _opt_str = option_rec.get("strike", _atm) if option_rec else _atm
                _opt_ltp = option_rec.get("ltp", 0) if option_rec else 0
                _opt_tgt = option_rec.get("premium_target", 0) if option_rec else 0
                _opt_sl  = option_rec.get("premium_sl", 0) if option_rec else 0
                _opt_avg = round((_opt_ltp + _opt_tgt) / 2, 0) if _opt_ltp and _opt_tgt else 0
                if _opt_ltp:
                    _sig_msg = (
                        f'SELL <b>{_nse_label} {int(_opt_str):,} PE</b>'
                        f' &nbsp;@ <b style="color:#ef4444;font-size:1.05em;">₹{_opt_ltp:.0f}</b>'
                        f' &nbsp;·&nbsp; <span style="color:#fbbf24;">Target ₹{_opt_tgt:.0f}</span>'
                        f' &nbsp;·&nbsp; <span style="color:#fb923c;">Avg ₹{_opt_avg:.0f}</span>'
                        f' &nbsp;·&nbsp; <span style="color:#ef4444;">SL ₹{_opt_sl:.0f}</span>'
                    )
                else:
                    _sig_msg = (
                        f'SELL <b>{_nse_label} {_atm:,} PE</b>'
                        f' &nbsp;<span style="color:#6b7280;font-size:0.85em;">@ ₹{spot_price:,.0f} · ATM Put</span>'
                    )
            else:
                _sig_msg = f'Sell <b>{disp_short}</b> @ ₹{spot_price:,.0f}'
        else:
            _t1, _t2 = pivots.get("R1", 0), pivots.get("S1", 0)
            _sl1, _sl2 = pivots.get("PP", 0), 0
            _sig_bg = "linear-gradient(135deg,#0e0e1a 0%,#12121f 100%)"
            _sig_border, _sig_accent = "#2a2a4a", "#9ca3af"
            _sig_arrow, _sig_label = "⏸", "NEUTRAL"
            _r1v, _s1v = pivots.get("R1", 0), pivots.get("S1", 0)
            if _has_fo:
                _ce_strike = _opt_strike(_r1v, active_sym_key)
                _pe_strike = _opt_strike(_s1v, active_sym_key)
                _sig_msg = (
                    f"<b>{_nse_label}</b> · "
                    f'<span style="color:#4caf50;">Break ₹{_r1v:,.0f} → <b>{_ce_strike:,} CE</b></span>'
                    f' &nbsp;|&nbsp; '
                    f'<span style="color:#ef4444;">Break ₹{_s1v:,.0f} → <b>{_pe_strike:,} PE</b></span>'
                )
            else:
                _sig_msg = (
                    f"<b>{disp_short}</b> · "
                    f'<span style="color:#4caf50;">Buy above ₹{_r1v:,.0f}</span>'
                    f' &nbsp;|&nbsp; '
                    f'<span style="color:#ef4444;">Sell below ₹{_s1v:,.0f}</span>'
                )
        _avg = round((_t1 + _t2) / 2, 2) if _t1 and _t2 else 0

        def _lvl(label, val, clr):
            if not val: return ""
            return (f'<div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);'
                    f'border-radius:5px;padding:4px 10px;text-align:center;min-width:62px;">'
                    f'<div style="color:#6b7280;font-size:0.5em;text-transform:uppercase;letter-spacing:0.5px;">{label}</div>'
                    f'<div style="color:{clr};font-size:0.8em;font-weight:700;margin-top:1px;">₹{val:,.0f}</div>'
                    f'</div>')

        _levels_html = "".join([
            _lvl("T1",  _t1,  "#4caf50"),
            _lvl("T2",  _t2,  "#22c55e"),
            _lvl("AVG", _avg, "#fbbf24"),
            _lvl("SL1", _sl1, "#f97316"),
            _lvl("SL2", _sl2, "#ef4444"),
        ])

        st.markdown(f"""
<div style="display:flex;justify-content:space-between;align-items:center;
            padding:6px 6px 4px;border-bottom:1px solid #2a2a4a;">
  <div style="display:flex;align-items:baseline;gap:8px;">
    <span style="color:#e8e8e8;font-size:1.2em;font-weight:700;">{disp_short}</span>
    <span style="color:#4b5563;font-size:0.65em;">NSE</span>
    <span style="color:#e8e8e8;font-size:1.35em;font-weight:700;">{spot_price:,.2f}</span>
    <span style="color:{chg_c};font-size:0.8em;font-weight:600;">{arrow} {abs(day_pct):.2f}%</span>
  </div>
  <div style="color:#4b5563;font-size:0.58em;">
    O:{df['Open'].iloc[0]:,.0f} &nbsp;H:{df['High'].max():,.0f} &nbsp;L:{df['Low'].min():,.0f}
  </div>
</div>
<div style="background:{_sig_bg};border:1px solid {_sig_border};border-left:3px solid {_sig_accent};
            border-radius:6px;padding:8px 10px 8px;margin:5px 0 3px;">
  <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
    <div>
      <span style="color:{_sig_accent};font-size:0.65em;font-weight:800;letter-spacing:1px;">{_sig_arrow} {_sig_label}</span>
      <div style="color:#e8e8e8;font-size:0.9em;font-weight:600;margin-top:2px;">{_sig_msg}</div>
      <div style="color:#6b7280;font-size:0.58em;margin-top:2px;">
        Target avg ₹{_avg:,.0f} &nbsp;·&nbsp; PP ₹{pivots.get("PP",0):,.0f}
      </div>
    </div>
    <div style="display:flex;gap:5px;flex-wrap:wrap;">{_levels_html}</div>
  </div>
</div>""", unsafe_allow_html=True)
    else:
        st.markdown(f'<div style="padding:7px 4px 9px;border-bottom:1px solid #2a2a4a;"><span style="color:#e8e8e8;font-size:1.2em;font-weight:700;">{active_sym_key}</span> <span style="color:#f59e0b;font-size:0.8em;">⟳ Loading...</span></div>', unsafe_allow_html=True)

    # ── Timeframe selector + Refresh ──
    tf_col, _rf_col, _spacer = st.columns([4, 1, 5])
    with tf_col:
        new_tf = st.radio("tf", ["1m","3m","5m","15m","1h","1D"],
            index=["1m","3m","5m","15m","1h","1D"].index(st.session_state.chart_tf),
            horizontal=True, key="tf_radio", label_visibility="collapsed")
        if new_tf != st.session_state.chart_tf:
            st.session_state.chart_tf = new_tf; st.cache_data.clear(); st.rerun()
    with _rf_col:
        if st.button("⟳", key="chart_refresh", help="Refresh chart data"):
            st.cache_data.clear(); st.rerun()

    # ── TradingView Lightweight Charts (open-source, our own data) ──
    import json as _json
    import streamlit.components.v1 as _stc

    _lc_candles = _df_to_lc_candles(df, st.session_state.chart_tf) if (data_ok and df is not None and not df.empty) else []
    _lc_json    = _json.dumps(_lc_candles)

    # Price lines: LTP + pivots
    _pl_js = []
    if data_ok and spot_price:
        _pl_js.append(f"cs.createPriceLine({{price:{spot_price},color:'#387ed1',lineWidth:1,lineStyle:1,axisLabelVisible:true,title:'LTP'}});")
    for _plbl, _pclr, _pls in [("R2","#ef4444",2),("R1","#f97316",2),("PP","#fbbf24",1),("S1","#22c55e",2),("S2","#16a34a",2)]:
        _pval = pivots.get(_plbl)
        if _pval and _pval > 0:
            _pl_js.append(f"cs.createPriceLine({{price:{_pval},color:'{_pclr}',lineWidth:1,lineStyle:{_pls},axisLabelVisible:true,title:'{_plbl}'}});")

    _sym_js      = active_sym_key.replace("'", "\\'")
    _tf_js       = st.session_state.chart_tf
    _fb_ltp      = spot_price or 0
    _pivots_json = _json.dumps({k: v for k, v in pivots.items() if v and v > 0})
    _chart_html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>*{{margin:0;padding:0;box-sizing:border-box;}}html,body{{background:#131722;overflow:hidden;width:100%;height:490px;}}</style>
</head><body>
<div id="c" style="width:100%;height:490px;"></div>
<script>
const SYMBOL = '{_sym_js}';
const TF     = '{_tf_js}';

// Embedded fallback — chart shows immediately even before API is available
const INIT_CANDLES = {_lc_json};
const INIT_LTP     = {_fb_ltp};
const INIT_PIVOTS  = {_pivots_json};

const chart = LightweightCharts.createChart(document.getElementById('c'), {{
  width: window.innerWidth, height: 490,
  layout: {{ background:{{type:'solid',color:'#131722'}}, textColor:'#9ca3af', fontSize:11 }},
  grid: {{ vertLines:{{color:'#1e1e2e'}}, horzLines:{{color:'#1e1e2e'}} }},
  crosshair: {{ mode:1 }},
  rightPriceScale: {{ borderColor:'#2a2a4a' }},
  timeScale: {{ borderColor:'#2a2a4a', timeVisible:true, secondsVisible:false, rightOffset:5 }},
}});
const cs = chart.addCandlestickSeries({{
  upColor:'#4caf50', downColor:'#ef4444',
  borderUpColor:'#4caf50', borderDownColor:'#ef4444',
  wickUpColor:'#4caf50', wickDownColor:'#ef4444',
}});

let ltpLine = null;
let pivotLines = {{}};
const PIVOT_COLORS = {{R2:'#ef4444',R1:'#f97316',PP:'#fbbf24',S1:'#22c55e',S2:'#16a34a'}};
const PIVOT_STYLES = {{R2:2,R1:2,PP:1,S1:2,S2:2}};

function drawPivots(pvt) {{
  Object.values(pivotLines).forEach(pl => cs.removePriceLine(pl));
  pivotLines = {{}};
  Object.entries(pvt).forEach(([k, v]) => {{
    if (v && v > 0)
      pivotLines[k] = cs.createPriceLine({{price:v,color:PIVOT_COLORS[k]||'#9ca3af',lineWidth:1,lineStyle:PIVOT_STYLES[k]||2,axisLabelVisible:true,title:k}});
  }});
}}

// ── Show embedded data immediately ──
if (INIT_CANDLES.length > 0) {{ cs.setData(INIT_CANDLES); chart.timeScale().fitContent(); }}
if (INIT_LTP > 0) ltpLine = cs.createPriceLine({{price:INIT_LTP,color:'#387ed1',lineWidth:1,lineStyle:1,axisLabelVisible:true,title:'LTP'}});
drawPivots(INIT_PIVOTS);

// ── Live upgrades via /api/live/* (requires nginx /api/ route on server) ──
async function apiLoadCandles() {{
  try {{
    const r = await fetch('/api/live/candles?key='+encodeURIComponent(SYMBOL)+'&tf='+TF, {{cache:'no-store'}});
    if (!r.ok) return;
    const d = await r.json();
    if (d.candles && d.candles.length > 0) {{ cs.setData(d.candles); chart.timeScale().fitContent(); }}
    if (d.pivots) drawPivots(d.pivots);
  }} catch(e) {{}}
}}

async function apiUpdateLTP() {{
  try {{
    const r = await fetch('/api/live/ltp?key='+encodeURIComponent(SYMBOL), {{cache:'no-store'}});
    if (!r.ok) return;
    const d = await r.json();
    if (d.price && d.price > 0) {{
      if (!ltpLine) ltpLine = cs.createPriceLine({{price:d.price,color:'#387ed1',lineWidth:1,lineStyle:1,axisLabelVisible:true,title:'LTP'}});
      else ltpLine.applyOptions({{price:d.price}});
    }}
  }} catch(e) {{}}
}}

apiLoadCandles();                         // try API on load (no-op if nginx not set up)
setInterval(apiUpdateLTP,   1000);        // LTP every 1s via API if available
setInterval(apiLoadCandles, 30000);       // Candles every 30s via API if available
window.addEventListener('resize', () => chart.resize(window.innerWidth, 490));
</script></body></html>"""

    _stc.html(_chart_html, height=492, scrolling=False)

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
#  OPTION CHAIN TAB
# ══════════════════════════════════════════════
with _oc_tab:
    nse_sym_oc = active_sym.get("nse","")

    if not nse_sym_oc:
        _is_bse = active_sym.get("yf","").startswith("^BSE")
        _is_mcx = active_sym.get("yf","").startswith(("CL=","NG=","GC=","SI="))
        if _is_bse:
            st.info("SENSEX options trade on BSE, not NSE. NSE option chain is not available for SENSEX.")
        elif _is_mcx:
            st.info("MCX commodities don't have options available in this terminal.")
        else:
            st.info("Option chain not available for this instrument.")
    else:
        oc_raw = _load_option_chain(nse_sym_oc)
        if oc_raw is None or "records" not in oc_raw:
            st.markdown(f'<div style="color:#f59e0b;font-size:0.76em;padding:8px 2px;">⟳ Could not load option chain for {nse_sym_oc}. Check Kite connection or retry.</div>', unsafe_allow_html=True)
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
<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:6px;margin-bottom:8px;">
  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:7px 10px;">
    <div style="color:#6b7280;font-size:0.52em;text-transform:uppercase;letter-spacing:0.5px;">SPOT</div>
    <div style="color:#e8e8e8;font-size:1em;font-weight:700;">{spot_oc:,.0f}</div>
  </div>
  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:7px 10px;">
    <div style="color:#6b7280;font-size:0.52em;text-transform:uppercase;letter-spacing:0.5px;">PCR</div>
    <div style="color:{pcr_c};font-size:1em;font-weight:700;">{stats["pcr"]}</div>
  </div>
  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:7px 10px;">
    <div style="color:#6b7280;font-size:0.52em;text-transform:uppercase;letter-spacing:0.5px;">MAX PAIN</div>
    <div style="color:#fbbf24;font-size:1em;font-weight:700;">{stats["max_pain"]:,}</div>
  </div>
  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:7px 10px;">
    <div style="color:#6b7280;font-size:0.52em;text-transform:uppercase;letter-spacing:0.5px;">SIGNAL</div>
    <div style="color:{pcr_c};font-size:0.9em;font-weight:600;">{stats["pcr_label"]}</div>
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
                visible = set(sorted_s[max(0,ai-12): ai+13])
                chain_rows = [r for r in chain_rows if r["strike"] in visible]

            max_ce_oi = max((r["ce_oi"] for r in chain_rows), default=1) or 1
            max_pe_oi = max((r["pe_oi"] for r in chain_rows), default=1) or 1

            if chain_rows:
                tbl = '<table style="width:100%;border-collapse:collapse;font-size:0.78em;">'
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
#  SCANNER TAB
# ══════════════════════════════════════════════
with _scan_tab:
    # Use curated sector universe (all stocks pinned in Sector Picks, deduplicated)
    _fo_syms = _SECTOR_UNIVERSE

    _sc_col1, _sc_col2, _sc_col3 = st.columns([3, 1, 4])
    with _sc_col1:
        _scan_tf = st.radio("scan_tf", ["5m","15m","1h","1D"],
            index=1, horizontal=True, key="scan_tf_radio", label_visibility="collapsed")
    with _sc_col2:
        if st.button("⟳", key="scan_refresh"):
            st.cache_data.clear(); st.rerun()
    with _sc_col3:
        _scan_filter = st.radio("scan_sig_filter", ["All","BUY","SELL","HOLD"],
            horizontal=True, key="scan_filter_radio", label_visibility="collapsed")

    _src_label = "Zerodha Kite · live data" if kite_live else "Kite not connected"
    st.markdown(f'<div style="color:#6b7280;font-size:0.62em;padding:2px 0 6px;">Scanning {len(_fo_syms)} stocks across all sectors · {_scan_tf} · {_src_label} · cached 2 min</div>', unsafe_allow_html=True)

    with st.spinner(f"Computing signals for {len(_fo_syms)} stocks..."):
        _scan_data = _load_scanner_signals(_fo_syms, _scan_tf, use_kite=kite_live)

    _buys  = sum(1 for v in _scan_data.values() if v.get("signal") == "BUY")
    _sells = sum(1 for v in _scan_data.values() if v.get("signal") == "SELL")
    _holds = len(_scan_data) - _buys - _sells

    st.markdown(f"""
<div style="display:flex;gap:6px;margin-bottom:8px;">
  <div style="background:#0a1f0a;border:1px solid #1e4d1e;border-radius:6px;padding:6px 10px;flex:1;text-align:center;">
    <div style="color:#4caf50;font-size:0.52em;text-transform:uppercase;">BUY</div>
    <div style="color:#4caf50;font-size:1.5em;font-weight:700;">{_buys}</div>
  </div>
  <div style="background:#1f0a0a;border:1px solid #4d1e1e;border-radius:6px;padding:6px 10px;flex:1;text-align:center;">
    <div style="color:#ef4444;font-size:0.52em;text-transform:uppercase;">SELL</div>
    <div style="color:#ef4444;font-size:1.5em;font-weight:700;">{_sells}</div>
  </div>
  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:6px 10px;flex:1;text-align:center;">
    <div style="color:#9ca3af;font-size:0.52em;text-transform:uppercase;">HOLD</div>
    <div style="color:#9ca3af;font-size:1.5em;font-weight:700;">{_holds}</div>
  </div>
  <div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:6px 10px;flex:2;text-align:center;">
    <div style="color:#6b7280;font-size:0.52em;text-transform:uppercase;">LOADED</div>
    <div style="color:#e8e8e8;font-size:1.5em;font-weight:700;">{len(_scan_data)}<span style="font-size:0.5em;color:#6b7280;">/{len(_fo_syms)}</span></div>
  </div>
</div>""", unsafe_allow_html=True)

    def _scan_sort_key(item):
        v = item[1]
        sig = v.get("signal","HOLD")
        return (0 if sig=="BUY" else (1 if sig=="SELL" else 2), -v.get("buy_count",0) if sig=="BUY" else (-v.get("sell_count",0) if sig=="SELL" else 0))

    _scan_rows = sorted(_scan_data.items(), key=_scan_sort_key)
    if _scan_filter != "All":
        _scan_rows = [(k, v) for k, v in _scan_rows if v.get("signal") == _scan_filter]

    if not _scan_rows:
        st.markdown('<div style="color:#6b7280;padding:20px;text-align:center;font-size:0.82em;">No signals loaded. Click ⟳ to scan.</div>', unsafe_allow_html=True)
    else:
        tbl = '<table style="width:100%;border-collapse:collapse;font-size:0.77em;">'
        tbl += ('<thead><tr style="background:#1e293b;">'
                '<th style="padding:4px 6px;color:#9ca3af;text-align:left;">SYMBOL</th>'
                '<th style="padding:4px 6px;color:#9ca3af;text-align:right;">PRICE</th>'
                '<th style="padding:4px 6px;color:#9ca3af;text-align:center;">RSI</th>'
                '<th style="padding:4px 6px;color:#9ca3af;text-align:center;">MACD</th>'
                '<th style="padding:4px 6px;color:#9ca3af;text-align:center;">ST</th>'
                '<th style="padding:4px 6px;color:#9ca3af;text-align:center;">VWAP</th>'
                '<th style="padding:4px 6px;color:#9ca3af;text-align:center;">SIGNAL</th>'
                '</tr></thead><tbody>')

        for sym_key, v in _scan_rows:
            sig   = v.get("signal","HOLD")
            rsi_v = v.get("rsi", 50)
            macd  = v.get("macd","--")
            st_v  = v.get("supertrend","--")
            vwap  = v.get("vwap","--")
            spot  = v.get("spot", 0)
            nse   = SYMBOLS.get(sym_key, {}).get("nse", sym_key)
            sel   = "?wl_select=" + urllib.parse.quote_plus(sym_key)

            sig_c  = "#4caf50" if sig=="BUY" else ("#ef4444" if sig=="SELL" else "#9ca3af")
            row_bg = "background:rgba(76,175,80,0.06);" if sig=="BUY" else ("background:rgba(239,68,68,0.06);" if sig=="SELL" else "")
            rsi_c  = "#ef4444" if rsi_v > 70 else ("#4caf50" if rsi_v < 30 else "#d1d5db")
            macd_c = "#4caf50" if macd=="BUY" else ("#ef4444" if macd=="SELL" else "#9ca3af")
            st_c   = "#4caf50" if st_v=="BULL" else "#ef4444"
            vwap_c = "#4caf50" if vwap=="BUY" else ("#ef4444" if vwap=="SELL" else "#9ca3af")

            tbl += f'<tr style="border-bottom:1px solid rgba(42,42,74,0.2);{row_bg}">'
            tbl += f'<td style="padding:4px 6px;"><a href="{sel}" style="color:#e8e8e8;text-decoration:none;font-weight:600;">{sym_key}</a> <span style="color:#4b5563;font-size:0.72em;">{nse}</span></td>'
            tbl += f'<td style="padding:4px 6px;color:#d1d5db;text-align:right;">{spot:,.2f}</td>'
            tbl += f'<td style="padding:4px 6px;color:{rsi_c};text-align:center;font-weight:600;">{rsi_v:.0f}</td>'
            tbl += f'<td style="padding:4px 6px;color:{macd_c};text-align:center;">{macd}</td>'
            tbl += f'<td style="padding:4px 6px;color:{st_c};text-align:center;">{st_v}</td>'
            tbl += f'<td style="padding:4px 6px;color:{vwap_c};text-align:center;">{vwap}</td>'
            tbl += f'<td style="padding:4px 6px;text-align:center;"><span style="color:{sig_c};font-weight:700;">{sig}</span></td>'
            tbl += '</tr>'

        tbl += '</tbody></table>'
        st.markdown(tbl, unsafe_allow_html=True)


# ══════════════════════════════════════════════
#  SECTOR PICKS TAB
# ══════════════════════════════════════════════
with _picks_tab:
    _pk_col1, _pk_col2, _pk_col3 = st.columns([4, 3, 1])
    with _pk_col1:
        _sector_choice = st.selectbox(
            "sector", list(SECTOR_STOCKS.keys()),
            key="sector_select", label_visibility="collapsed"
        )
    with _pk_col2:
        _picks_tf = st.radio("picks_tf", ["5m","15m","1h","1D"],
            index=1, horizontal=True, key="picks_tf_radio", label_visibility="collapsed")
    with _pk_col3:
        if st.button("⟳", key="picks_refresh"):
            st.cache_data.clear(); st.rerun()

    _sector_syms = tuple(SECTOR_STOCKS.get(_sector_choice, []))
    st.markdown(
        f'<div style="color:#6b7280;font-size:0.62em;padding:2px 0 8px;">'
        f'Scoring {len(_sector_syms)} stocks in <b style="color:#e8e8e8;">{_sector_choice}</b> '
        f'· {_picks_tf} · RSI + MACD + Supertrend + VWAP + Volume · cached 2 min</div>',
        unsafe_allow_html=True
    )

    with st.spinner(f"Analysing {len(_sector_syms)} stocks..."):
        _sec_data = _load_sector_signals(_sector_syms, _picks_tf, use_kite=kite_live)

    # Sort by score descending, then by direction (BUY before SELL before NEUTRAL)
    _dir_order = {"BUY": 0, "SELL": 1, "NEUTRAL": 2}
    _sec_ranked = sorted(
        _sec_data.items(),
        key=lambda x: (-x[1]["score"], _dir_order.get(x[1]["direction"], 2))
    )
    _top4 = _sec_ranked[:4]

    # Sector summary strip
    _s_buys  = sum(1 for _, v in _sec_data.items() if v["direction"] == "BUY")
    _s_sells = sum(1 for _, v in _sec_data.items() if v["direction"] == "SELL")
    _s_neut  = len(_sec_data) - _s_buys - _s_sells
    _sec_lean = "BULLISH" if _s_buys > _s_sells else ("BEARISH" if _s_sells > _s_buys else "NEUTRAL")
    _lean_c   = "#4caf50" if _sec_lean == "BULLISH" else ("#ef4444" if _sec_lean == "BEARISH" else "#9ca3af")

    st.markdown(f"""
<div style="background:#12121f;border:1px solid #2a2a4a;border-radius:6px;padding:8px 12px;
            margin-bottom:10px;display:flex;align-items:center;gap:16px;">
  <div><span style="color:#6b7280;font-size:0.58em;text-transform:uppercase;">Sector Bias</span>
       <span style="color:{_lean_c};font-size:0.88em;font-weight:700;margin-left:6px;">{_sec_lean}</span></div>
  <div style="display:flex;gap:10px;font-size:0.72em;">
    <span style="color:#4caf50;">▲ {_s_buys} BUY</span>
    <span style="color:#ef4444;">▼ {_s_sells} SELL</span>
    <span style="color:#6b7280;">⏸ {_s_neut} NEUTRAL</span>
    <span style="color:#4b5563;">of {len(_sec_data)} loaded</span>
  </div>
  <div style="margin-left:auto;color:#6b7280;font-size:0.6em;">Top 4 by signal strength →</div>
</div>""", unsafe_allow_html=True)

    if not _top4:
        st.markdown('<div style="color:#6b7280;padding:20px;text-align:center;">No data loaded. Click ⟳ to scan.</div>', unsafe_allow_html=True)
    else:
        for _rank, (_sym, _sv) in enumerate(_top4, 1):
            _dir   = _sv["direction"]
            _score = _sv["score"]
            _spot  = _sv["spot"]
            _dpct  = _sv["day_pct"]
            _vol_s = _sv["vol_spike"]

            _dc    = "#4caf50" if _dpct >= 0 else "#ef4444"
            _darr  = "▲" if _dpct >= 0 else "▼"
            _dir_c = "#4caf50" if _dir == "BUY" else ("#ef4444" if _dir == "SELL" else "#9ca3af")
            _card_bg   = "rgba(76,175,80,0.05)"  if _dir=="BUY"  else ("rgba(239,68,68,0.05)" if _dir=="SELL" else "rgba(18,18,31,1)")
            _card_bdr  = "#1e4d1e" if _dir=="BUY" else ("#4d1e1e" if _dir=="SELL" else "#2a2a4a")
            _card_acc  = "#4caf50" if _dir=="BUY" else ("#ef4444" if _dir=="SELL" else "#6b7280")

            # Option recommendation
            _step = (50 if _spot > 20000 else (100 if _spot > 5000 else (50 if _spot > 2000 else (10 if _spot > 500 else 5))))
            _atm  = int(round(_spot / _step) * _step)
            _opt_type = "CE" if _dir == "BUY" else ("PE" if _dir == "SELL" else "--")
            _prem_est = round(_spot * 0.018, 1)   # ~1.8% of spot = rough ATM premium
            _tgt_est  = round(_prem_est * 1.7, 1)  # 70% gain target
            _sl_est   = round(_prem_est * 0.5, 1)  # 50% SL

            # Signal dots (filled vs empty)
            _ind_vals = [
                ("RSI",  _sv["rsi"],        _sv["rsi"] < 30 or _sv["rsi"] > 70, _dir),
                ("MACD", _sv["macd"],        _sv["macd"] == _dir,               _dir),
                ("ST",   _sv["supertrend"], (_sv["supertrend"]=="BULL")==(_dir=="BUY"), _dir),
                ("VWAP", _sv["vwap"],        _sv["vwap"] == _dir,               _dir),
                ("VOL",  "SPIKE" if _vol_s else "AVG", _vol_s,                  _dir),
            ]

            _dots = ""
            for _iname, _ival, _agrees, _d in _ind_vals:
                _dc2 = _card_acc if _agrees else "#2a2a4a"
                _dots += f'<span style="color:{_dc2};font-size:0.9em;" title="{_iname}: {_ival}">●</span>'

            _ind_detail = ""
            for _iname, _ival, _agrees, _d in _ind_vals:
                _ic = _card_acc if _agrees else "#4b5563"
                _iv_str = f"{_ival:.0f}" if isinstance(_ival, float) else str(_ival)
                _ind_detail += (
                    f'<div style="background:#0e0e1a;border:1px solid #2a2a4a;border-radius:4px;'
                    f'padding:3px 7px;text-align:center;">'
                    f'<div style="color:#6b7280;font-size:0.48em;text-transform:uppercase;">{_iname}</div>'
                    f'<div style="color:{_ic};font-size:0.7em;font-weight:600;">{_iv_str}</div>'
                    f'</div>'
                )

            # Build option trade box separately (avoids f-string ternary issues)
            if _dir in ("BUY", "SELL"):
                _opt_box = (
                    f'<div style="background:#0e0e1a;border:1px solid {_card_bdr};border-radius:5px;padding:8px 12px;min-width:180px;">'
                    f'<div style="color:{_card_acc};font-size:0.58em;font-weight:800;text-transform:uppercase;letter-spacing:0.5px;">Option Trade</div>'
                    f'<div style="color:#e8e8e8;font-size:0.9em;font-weight:700;margin-top:2px;">{_sym} {_atm} {_opt_type}</div>'
                    f'<div style="display:flex;gap:10px;margin-top:5px;font-size:0.68em;">'
                    f'<span style="color:#6b7280;">Entry <span style="color:#e8e8e8;font-weight:600;">~&#8377;{_prem_est}</span></span>'
                    f'<span style="color:#4caf50;">T &#8377;{_tgt_est}</span>'
                    f'<span style="color:#ef4444;">SL &#8377;{_sl_est}</span>'
                    f'</div>'
                    f'<div style="color:#4b5563;font-size:0.55em;margin-top:3px;">Approx ATM premium · verify before trading</div>'
                    f'</div>'
                )
            else:
                _opt_box = '<div style="color:#6b7280;font-size:0.75em;padding:8px;">No clear option play — wait for stronger signal.</div>'

            _vol_badge = '<span style="color:#f59e0b;font-size:0.58em;font-weight:700;background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.2);border-radius:10px;padding:1px 6px;">&#9889; VOL SPIKE</span>' if _vol_s else ''

            _card_html = (
                f'<div style="background:{_card_bg};border:1px solid {_card_bdr};border-left:3px solid {_card_acc};'
                f'border-radius:6px;padding:10px 12px;margin-bottom:8px;">'
                f'<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;flex-wrap:wrap;">'

                f'<div style="flex:1;min-width:160px;">'
                f'<div style="display:flex;align-items:center;gap:8px;">'
                f'<span style="color:#6b7280;font-size:0.58em;font-weight:700;">#{_rank}</span>'
                f'<span style="color:#e8e8e8;font-size:1.05em;font-weight:700;">{_sym}</span>'
                f'<span style="color:{_dir_c};font-size:0.65em;font-weight:800;background:{_card_bg};'
                f'border:1px solid {_card_bdr};border-radius:10px;padding:1px 7px;">{_dir}</span>'
                f'{_vol_badge}'
                f'</div>'
                f'<div style="margin-top:3px;">'
                f'<span style="color:#e8e8e8;font-size:0.9em;font-weight:700;">&#8377;{_spot:,.2f}</span>'
                f'<span style="color:{_dc};font-size:0.72em;margin-left:6px;">{_darr} {abs(_dpct):.2f}%</span>'
                f'</div>'
                f'<div style="margin-top:5px;display:flex;gap:3px;">{_dots}'
                f'<span style="color:#6b7280;font-size:0.6em;margin-left:4px;">{_score}/5 signals</span>'
                f'</div>'
                f'</div>'

                f'<div style="display:flex;gap:4px;flex-wrap:wrap;align-items:center;">{_ind_detail}</div>'

                f'{_opt_box}'

                f'</div></div>'
            )
            st.markdown(_card_html, unsafe_allow_html=True)
            # Action buttons — navigate to Chart or Option Chain for this stock
            _ab1, _ab2, _ab_rest = st.columns([1, 1, 6])
            with _ab1:
                if st.button("📈 Chart", key=f"go_chart_{_sym}_{_rank}", use_container_width=True):
                    st.session_state.active_symbol = _sym
                    st.session_state.navigate_to_tab = 0
                    st.rerun()
            with _ab2:
                if st.button("⛓ Chain", key=f"go_oc_{_sym}_{_rank}", use_container_width=True):
                    st.session_state.active_symbol = _sym
                    st.session_state.navigate_to_tab = 1
                    st.rerun()

        if len(_sec_ranked) > 4:
            _rest = _sec_ranked[4:]
            with st.expander(f"All {len(_sec_ranked)} stocks in {_sector_choice}"):
                _rest_tbl = '<table style="width:100%;border-collapse:collapse;font-size:0.76em;">'
                _rest_tbl += '<thead><tr style="background:#1e293b;"><th style="padding:4px 6px;text-align:left;color:#9ca3af;">STOCK</th><th style="padding:4px 6px;text-align:right;color:#9ca3af;">PRICE</th><th style="padding:4px 6px;text-align:center;color:#9ca3af;">SCORE</th><th style="padding:4px 6px;text-align:center;color:#9ca3af;">RSI</th><th style="padding:4px 6px;text-align:center;color:#9ca3af;">MACD</th><th style="padding:4px 6px;text-align:center;color:#9ca3af;">ST</th><th style="padding:4px 6px;text-align:center;color:#9ca3af;">SIGNAL</th></tr></thead><tbody>'
                for _s, _v in _rest:
                    _dc3 = "#4caf50" if _v["direction"]=="BUY" else ("#ef4444" if _v["direction"]=="SELL" else "#9ca3af")
                    _rest_tbl += f'<tr style="border-bottom:1px solid rgba(42,42,74,0.2);">'
                    _rest_tbl += f'<td style="padding:3px 6px;color:#e8e8e8;font-weight:600;">{_s}</td>'
                    _rest_tbl += f'<td style="padding:3px 6px;color:#d1d5db;text-align:right;">₹{_v["spot"]:,.0f}</td>'
                    _rest_tbl += f'<td style="padding:3px 6px;text-align:center;color:#fbbf24;">{_v["score"]}/5</td>'
                    _rest_tbl += f'<td style="padding:3px 6px;text-align:center;color:#d1d5db;">{_v["rsi"]:.0f}</td>'
                    _rest_tbl += f'<td style="padding:3px 6px;text-align:center;color:#d1d5db;">{_v["macd"]}</td>'
                    _rest_tbl += f'<td style="padding:3px 6px;text-align:center;color:#d1d5db;">{_v["supertrend"]}</td>'
                    _rest_tbl += f'<td style="padding:3px 6px;text-align:center;"><span style="color:{_dc3};font-weight:700;">{_v["direction"]}</span></td>'
                    _rest_tbl += '</tr>'
                _rest_tbl += '</tbody></table>'
                st.markdown(_rest_tbl, unsafe_allow_html=True)


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
        try:
            if data_ok and rsi_d and st_d and vwap_d:
                _rv = rsi_d.get("value", 50)
                rsi_val2 = float(_rv) if _rv is not None else 50
                if not (0 <= rsi_val2 <= 100): rsi_val2 = 50
                _pcr = oi_d.get("pcr", 0.8) if oi_d else 0.8
                try: _pcr = float(_pcr); _pcr = 0.8 if not (0 <= _pcr <= 10) else _pcr
                except Exception: _pcr = 0.8
                sent_score = min(100, max(0,
                    int((rsi_val2-30)/40*25) +
                    (25 if (st_d and st_d.get("direction")==1) else 0) +
                    (25 if (vwap_d and vwap_d.get("signal")=="BUY") else 0) +
                    (0 if not oi_d else min(25, max(0, int(_pcr*25))))
                ))
        except Exception:
            sent_score = 50
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
    f'Auto-refreshes every {"60s" if (mkt_open and kite_live) else "60s" if mkt_open else "5min"}. Prices update every 2s via live polling.'
    f'</div>',
    unsafe_allow_html=True,
)
