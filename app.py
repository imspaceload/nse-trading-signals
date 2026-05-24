import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
from datetime import datetime
import pytz
import concurrent.futures
import pandas as pd
import json

from config import (
    SYMBOLS, STOP_LOSS_PCT, TARGET_PCT,
    RSI_PERIOD, RSI_OVERBOUGHT, RSI_OVERSOLD,
    EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER,
)
from data_fetcher import (
    get_spot_price, get_intraday_data, get_option_chain_data,
    get_option_recommendation, is_market_open, get_current_option_ltp,
)
from indicators import (
    compute_rsi, compute_macd, compute_supertrend, compute_vwap,
    evaluate_oi, generate_signal, compute_all_signals,
    compute_support_resistance,
)
from news_scraper import scrape_moneycontrol_news
from claude_analyzer import analyze_market
from notifier import format_signal_chat, send_signal_email
from trades import (
    create_trade, close_trade, get_open_trades, get_closed_trades,
    delete_trade,
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

st.set_page_config(page_title="Options Terminal", page_icon="⚡", layout="wide")

# Auto-refresh: 60s during market hours, 5 min when closed
_refresh_ms = 60_000 if is_market_open() else 300_000
st_autorefresh(interval=_refresh_ms, limit=0, key="live_refresh")

# ── Kite-style CSS ──
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    * { font-family: 'Inter', -apple-system, sans-serif !important; }
    .block-container { padding-top: 0.5rem; max-width: 100%; padding-left: 1rem; padding-right: 1rem; }

    /* Sidebar - Kite dark */
    div[data-testid="stSidebar"] { background: #1b1b2f; border-right: 1px solid #2a2a4a; }
    div[data-testid="stSidebar"] .stTextInput input { background: #12121f; border: 1px solid #2a2a4a; color: #e8e8e8; border-radius: 4px; font-size: 13px; }
    div[data-testid="stSidebar"] .stSelectbox > div > div { background: #12121f; border: 1px solid #2a2a4a; border-radius: 4px; }

    /* Action panels - clean Kite style */
    .action-panel { padding: 16px 20px; border-radius: 4px; margin: 8px 0; }
    .action-buy { background: #e8f5e9; border-left: 4px solid #4caf50; }
    .action-buy h2, .action-buy .step { color: #1b5e20 !important; }
    .action-buy .step b { color: #2e7d32 !important; }
    .action-sell { background: #ffebee; border-left: 4px solid #f44336; }
    .action-sell h2, .action-sell .step { color: #b71c1c !important; }
    .action-sell .step b { color: #c62828 !important; }
    .action-hold { background: #1e1e2e; border-left: 4px solid #ff9800; }
    .action-panel h2 { margin: 0 0 8px 0; font-size: 1.3em; font-weight: 600; }
    .action-panel .step { font-size: 0.9em; margin: 4px 0; padding: 6px 10px; background: rgba(0,0,0,0.05); border-radius: 4px; }

    /* Option card - clean */
    .option-card { background: #12121f; padding: 14px 16px; border-radius: 4px; border: 1px solid #2a2a4a; margin: 8px 0; }
    .option-card h3 { margin: 0 0 8px 0; color: #9ca3af; font-size: 0.85em; text-transform: uppercase; letter-spacing: 0.5px; }
    .option-card .contract { font-size: 1.2em; font-weight: 700; color: #e8e8e8; margin: 4px 0; }
    .option-card .detail { color: #9ca3af; font-size: 0.85em; margin: 2px 0; }

    /* Signal feed - compact cards */
    .chat-container { max-height: 450px; overflow-y: auto; padding: 4px; }
    .chat-msg { padding: 10px 12px; border-radius: 4px; margin: 4px 0; font-size: 0.82em; line-height: 1.5; border-left: 3px solid; }
    .chat-buy { background: #12261e; color: #a5d6a7; border-left-color: #4caf50; }
    .chat-sell { background: #2a1215; color: #ef9a9a; border-left-color: #f44336; }
    .chat-hold { background: #1e1e2e; color: #ffe0b2; border-left-color: #ff9800; }
    .chat-time { font-size: 0.7em; color: rgba(255,255,255,0.35); text-align: right; margin-top: 3px; }

    /* Indicator cards - Kite minimal */
    .indicator-card { background: #12121f; padding: 12px; border-radius: 4px; border: 1px solid #2a2a4a; margin: 3px 0; text-align: center; }
    .indicator-card h4 { margin: 0 0 4px 0; color: #6b7280; font-size: 0.7em; text-transform: uppercase; letter-spacing: 1px; font-weight: 500; }
    .indicator-card .value { font-size: 1.3em; font-weight: 600; color: #e8e8e8; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 2px; font-size: 0.65em; font-weight: 600; color: white; margin-top: 4px; }
    .badge-buy { background: #4caf50; }
    .badge-sell { background: #f44336; }
    .badge-neutral { background: #616161; }

    /* Tables - clean */
    .signal-table { width: 100%; border-collapse: collapse; font-size: 0.8em; }
    .signal-table th { background: #12121f; color: #6b7280; padding: 8px 10px; text-align: left; font-weight: 500; text-transform: uppercase; font-size: 0.85em; letter-spacing: 0.5px; border-bottom: 1px solid #2a2a4a; }
    .signal-table td { padding: 8px 10px; border-bottom: 1px solid #1a1a2e; color: #d1d5db; }

    .sms-log-table, .sub-table { width: 100%; border-collapse: collapse; font-size: 0.8em; }
    .sms-log-table th, .sub-table th { background: #12121f; color: #6b7280; padding: 6px 10px; text-align: left; font-weight: 500; border-bottom: 1px solid #2a2a4a; }
    .sms-log-table td, .sub-table td { padding: 6px 10px; border-bottom: 1px solid #1a1a2e; color: #d1d5db; }

    /* News */
    .news-item { background: #12121f; padding: 10px 14px; border-radius: 4px; margin: 4px 0; border-left: 3px solid #616161; }
    .news-item.bullish { border-left-color: #4caf50; }
    .news-item.bearish { border-left-color: #f44336; }
    .analysis-box { background: #12121f; padding: 14px; border-radius: 4px; border: 1px solid #2a2a4a; }

    /* Auto SMS banner */
    .auto-sms-banner { background: #12121f; border: 1px solid #2a2a4a; border-radius: 4px; padding: 10px 14px; margin: 6px 0; }
    .auto-sms-banner .title { color: #e8e8e8; font-weight: 600; font-size: 0.88em; }
    .auto-sms-banner .info { color: #6b7280; font-size: 0.78em; margin-top: 3px; }

    .alert-banner { animation: pulse 2s infinite; }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.85; } }

    /* Hide Streamlit branding */
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    header[data-testid="stHeader"] { background: #0e0e1a; border-bottom: 1px solid #2a2a4a; }

    /* Watchlist buttons — look like clean rows */
    div[data-testid="stSidebar"] button[kind="secondary"][key^="wl_"],
    div[data-testid="stSidebar"] div[data-testid="stButton"] button {
        background: transparent !important;
        border: none !important;
        border-bottom: 1px solid #1a1a2e !important;
        border-radius: 0 !important;
        color: #d1d5db !important;
        font-size: 0.82em !important;
        font-weight: 500 !important;
        padding: 8px 4px !important;
        text-align: left !important;
        transition: background 0.15s !important;
    }
    div[data-testid="stSidebar"] div[data-testid="stButton"] button:hover {
        background: rgba(99,102,241,0.1) !important;
    }
    /* Keep Refresh button styled as primary */
    div[data-testid="stSidebar"] button[kind="primary"] {
        background: #387ed1 !important;
        border: none !important;
        border-radius: 6px !important;
        color: white !important;
        font-weight: 600 !important;
        padding: 8px 16px !important;
    }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════
#  SIDEBAR
# ══════════════════════════════════════════

def _make_sym(name: str) -> dict:
    """Auto-construct yf/nse/tv keys for any NSE symbol."""
    n = name.strip().upper()
    return {"yf": f"{n}.NS", "nse": n, "tv": f"NSE:{n}"}

def _atm_strike(price: float) -> int:
    """Smart ATM strike rounding based on price level."""
    if price <= 0:
        return 0
    if price < 50:
        step = 2.5
    elif price < 250:
        step = 5
    elif price < 1000:
        step = 10  # IDEA ₹13 → 15, TATAPOWER ₹400 → 400
    elif price < 5000:
        step = 50
    else:
        step = 100  # NIFTY, RELIANCE, etc.
    return int(round(price / step) * step)

with st.sidebar:
    # ── Kite-style header ──
    now = datetime.now(IST)
    mkt_status = "LIVE" if is_market_open() else "CLOSED"
    mkt_color = "#4caf50" if is_market_open() else "#f44336"
    st.markdown(f"""
    <div style="padding:8px 0 12px 0;border-bottom:1px solid #2a2a4a;margin-bottom:12px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <span style="color:#e8e8e8;font-size:1.1em;font-weight:700;">⚡ Options Terminal</span>
            <span style="background:{mkt_color};color:white;padding:2px 8px;border-radius:2px;font-size:0.65em;font-weight:600;">{mkt_status}</span>
        </div>
        <div style="color:#6b7280;font-size:0.75em;margin-top:4px;">{now.strftime("%d %b %Y, %I:%M %p IST")}</div>
    </div>
    """, unsafe_allow_html=True)

    # ── Symbol search (only search, no dropdown) ──
    custom_sym = st.text_input("Search", placeholder="Type symbol... IDEA, RELIANCE", key="custom_sym", label_visibility="collapsed")

    if custom_sym.strip():
        custom_upper = custom_sym.strip().upper()
        match = [k for k in SYMBOLS if custom_upper == k.upper() or custom_upper == SYMBOLS[k].get("nse", "").upper()]
        if match:
            selected_symbol = match[0]
            sym = SYMBOLS[selected_symbol]
        else:
            selected_symbol = custom_upper
            sym = _make_sym(custom_upper)
    else:
        # No default — user must type a symbol
        selected_symbol = None
        sym = None

    # ── Chart settings in a row ──
    c1, c2 = st.columns(2)
    with c1:
        chart_period = st.selectbox("Period", ["1d", "5d", "1mo"], index=0, label_visibility="collapsed")
    with c2:
        chart_interval = st.selectbox("Interval", ["1m", "5m", "15m", "30m", "1h"], index=1, label_visibility="collapsed")

    if st.button("↻ Refresh", use_container_width=True, type="primary"):
        st.cache_data.clear()
        st.rerun()

    # ── Watchlist (saved to Supabase) ──
    saved_watchlist = get_watchlist()

    # Fetch prices during market hours
    if saved_watchlist and is_market_open():
        @st.cache_data(ttl=120)
        def fetch_watchlist_prices(symbols_tuple):
            results = {}
            def _fetch(name):
                try:
                    sym_info = SYMBOLS.get(name, _make_sym(name))
                    return name, get_spot_price(sym_info["yf"])
                except Exception:
                    return name, None
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
                for f in concurrent.futures.as_completed([ex.submit(_fetch, n) for n in symbols_tuple]):
                    n, p = f.result()
                    results[n] = p
            return results
        wl_prices = fetch_watchlist_prices(tuple(saved_watchlist))
    else:
        wl_prices = {}

    # Watchlist header
    subs = get_subscribers()
    sms_clr = "#4caf50" if len(subs) > 0 else "#616161"
    sms_label = "ACTIVE" if len(subs) > 0 else "NO SUBS"

    st.markdown(f"""
    <div style="margin-top:14px;display:flex;justify-content:space-between;align-items:center;">
        <span style="color:#6b7280;font-size:0.65em;text-transform:uppercase;letter-spacing:1px;">Watchlist · {len(saved_watchlist)}</span>
        <span style="color:#9ca3af;font-size:0.6em;">📱 {len(subs)} sub · <span style="color:{sms_clr};">{sms_label}</span></span>
    </div>
    """, unsafe_allow_html=True)

    # Clickable watchlist items — each button loads that symbol
    for wl_name in saved_watchlist:
        p = wl_prices.get(wl_name)
        nse_s = SYMBOLS.get(wl_name, {}).get("nse", wl_name)
        display_name = nse_s if nse_s else wl_name
        price_str = f"₹{p:,.2f}" if p else "--"
        btn_label = f"{display_name}  ·  {price_str}"
        if st.button(btn_label, key=f"wl_{wl_name}", use_container_width=True):
            st.session_state["custom_sym"] = wl_name
            st.rerun()

    if not saved_watchlist:
        st.markdown('<div style="color:#4b5563;font-size:0.75em;padding:4px 0;">Type below to add</div>', unsafe_allow_html=True)

    # Add / Remove input
    wl_input = st.text_input("Watchlist", placeholder="+ IDEA  or  - COFORGE", key="wl_input", label_visibility="collapsed")
    if wl_input.strip():
        inp = wl_input.strip()
        if inp.startswith("-"):
            sym_to_remove = inp.lstrip("- ").upper()
            if remove_from_watchlist(sym_to_remove):
                st.rerun()
        else:
            sym_to_add = inp.lstrip("+ ").upper()
            if add_to_watchlist(sym_to_add):
                st.rerun()

    # Email config — hidden, no UI widget, just use env vars
    email_on = bool(EMAIL_SENDER and EMAIL_RECEIVER)
    sender = EMAIL_SENDER
    app_pwd = EMAIL_PASSWORD
    receiver = EMAIL_RECEIVER


# ══════════════════════════════════════════
#  EMPTY STATE — no symbol selected
# ══════════════════════════════════════════

if selected_symbol is None:
    st.markdown("""
    <div style="text-align:center;padding:80px 20px;">
        <div style="font-size:3em;margin-bottom:16px;">⚡</div>
        <div style="color:#e8e8e8;font-size:1.4em;font-weight:700;margin-bottom:8px;">Options Terminal</div>
        <div style="color:#6b7280;font-size:0.95em;margin-bottom:24px;">Type a symbol in the sidebar to get started</div>
        <div style="color:#4b5563;font-size:0.82em;">Examples: IDEA, RELIANCE, HDFCBANK, TCS, NIFTY</div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()


# ══════════════════════════════════════════
#  DATA FETCHING
# ══════════════════════════════════════════

@st.cache_data(ttl=55)
def fetch_data(yf_symbol, nse_symbol, period, interval):
    spot, df, oi = None, pd.DataFrame(), None
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            price_future = executor.submit(get_spot_price, yf_symbol)
            df_future = executor.submit(get_intraday_data, yf_symbol, period, interval)
            oi_future = executor.submit(get_option_chain_data, nse_symbol) if nse_symbol else None

            try:
                spot = price_future.result(timeout=10)
            except Exception:
                spot = None
            try:
                df = df_future.result(timeout=10)
            except Exception:
                df = pd.DataFrame()
            try:
                oi = oi_future.result(timeout=8) if oi_future else None
            except Exception:
                oi = None
    except Exception:
        pass
    return spot, df, oi

@st.cache_data(ttl=300)
def fetch_news():
    return scrape_moneycontrol_news()

def compute_for_symbol(yf_sym, nse_sym, period, interval):
    spot, df, oi_data = fetch_data(yf_sym, nse_sym, period, interval)
    if df.empty or spot is None:
        return None
    r = compute_rsi(df)
    m = compute_macd(df)
    st_data = compute_supertrend(df)
    v = compute_vwap(df)
    o = evaluate_oi(oi_data)
    sig = generate_signal(r, m, st_data, v, o, spot)
    sigs = compute_all_signals(df, interval)
    opt = None
    if sig["action"] in ("BUY", "SELL") and nse_sym:
        try:
            opt = get_option_recommendation(nse_sym, spot, sig["action"])
        except Exception:
            opt = None
    return {
        "spot": spot, "df": df, "oi_data": oi_data,
        "rsi": r, "macd": m, "supertrend": st_data, "vwap": v, "oi": o,
        "signal": sig, "all_signals": sigs, "option_rec": opt,
    }


# Fetch data
with st.spinner(f"Loading {selected_symbol} data..."):
    try:
        inst_data = compute_for_symbol(sym["yf"], sym["nse"], chart_period, chart_interval)
    except Exception:
        inst_data = None
    try:
        news = fetch_news()
    except Exception:
        news = []

data_ok = inst_data is not None
sms_sent_this_run = False
sms_sent_count = 0
sms_fail_count = 0

if data_ok:
    spot_price = inst_data["spot"]
    df = inst_data["df"]
    signal = inst_data["signal"]
    option_rec = inst_data["option_rec"]
    all_signals = inst_data["all_signals"]
    rsi = inst_data["rsi"]
    macd_data = inst_data["macd"]
    supertrend = inst_data["supertrend"]
    vwap_data = inst_data["vwap"]
    oi_data = inst_data["oi"]
    action = signal["action"]

    # ══════════════════════════════════════════
    #  AUTO SIGNAL → AUTO TRADE → AUTO SMS
    #  This is the brain: no manual work needed
    # ══════════════════════════════════════════

    alert_key = f"last_auto_signal_{selected_symbol}"
    cooldown_key = f"last_signal_time_{selected_symbol}"
    last_auto = st.session_state.get(alert_key, None)
    last_signal_time = st.session_state.get(cooldown_key, None)

    # 15-minute cooldown: no new signal of ANY type can fire for same instrument
    cooldown_ok = True
    if last_signal_time is not None:
        elapsed = (datetime.now(IST) - last_signal_time).total_seconds()
        if elapsed < 900:  # 15 minutes = 900 seconds
            cooldown_ok = False

    if action in ("BUY", "SELL") and action != last_auto and cooldown_ok:
        st.session_state[alert_key] = action
        st.session_state[cooldown_key] = datetime.now(IST)

        # ── 1. Auto-create trade from signal ──
        opt_type = "CE" if action == "BUY" else "PE"
        if option_rec:
            auto_trade = create_trade(
                instrument=selected_symbol,
                strike=option_rec["strike"],
                option_type=opt_type,
                expiry=option_rec["expiry"],
                entry_price=option_rec["ltp"],
                target_price=option_rec["premium_target"],
                stop_loss=option_rec["premium_sl"],
                quantity=1,
                lot_size=option_rec["lot_size"],
            )
            auto_trade["averaging_price"] = option_rec.get("premium_avg", round(option_rec["ltp"] * 0.7, 2))
        else:
            auto_trade = create_trade(
                instrument=selected_symbol,
                strike=round(spot_price / 100) * 100,
                option_type=opt_type,
                expiry="Weekly",
                entry_price=spot_price,
                target_price=signal["target"] if signal["target"] else round(spot_price * 1.01, 2),
                stop_loss=signal["stop_loss"] if signal["stop_loss"] else round(spot_price * 0.997, 2),
                quantity=1,
                lot_size=1,
            )

        # ── 2. Auto-send SMS to ALL subscribers ──
        sms_results = send_sms_to_all(auto_trade, action="BUY")
        sms_sent_count = sum(1 for r in sms_results if r.get("status") != "failed") if sms_results else 0
        sms_fail_count = sum(1 for r in sms_results if r.get("status") == "failed") if sms_results else 0
        sms_sent_this_run = True

        # ── 3. Auto-send email ──
        if email_on and sender and app_pwd and receiver:
            send_signal_email(sender, app_pwd, receiver, selected_symbol, signal, option_rec)

        # ── 4. Browser sound alert ──
        alert_msg = f"{action} {selected_symbol} @₹{spot_price:,.0f}"
        components.html(f"""
<script>
var ctx = new (window.AudioContext || window.webkitAudioContext)();
function beep(f,d){{var o=ctx.createOscillator();o.type='sine';o.frequency.value=f;o.connect(ctx.destination);o.start();setTimeout(function(){{o.stop();}},d);}}
beep({'880' if action == 'BUY' else '440'}, 300);
setTimeout(function(){{beep({'880' if action == 'BUY' else '440'}, 300);}}, 400);
setTimeout(function(){{beep({'1100' if action == 'BUY' else '330'}, 500);}}, 800);
if(Notification.permission==='granted'){{new Notification('Trading Signal!',{{body:'{alert_msg}',requireInteraction:true}});}}
else if(Notification.permission!=='denied'){{Notification.requestPermission();}}
</script>
""", height=0)

    elif action == "HOLD":
        st.session_state[alert_key] = "HOLD"

    # ══════════════════════════════════════════
    #  AUTO-CLOSE: check open trades for SL / Target hit
    # ══════════════════════════════════════════

    open_trades_check = get_open_trades()
    for t in open_trades_check:
        # Look up the NSE symbol for this trade's instrument
        t_sym_info = SYMBOLS.get(t["instrument"], {})
        t_nse = t_sym_info.get("nse", "")
        if not t_nse:
            continue  # can't fetch option LTP without NSE symbol

        # Fetch CURRENT option premium — this is what we compare SL/target against
        current_ltp = get_current_option_ltp(
            t_nse, t["strike"], t["option_type"], t["expiry"]
        )
        if current_ltp is None:
            continue  # fetch failed — skip, don't false-trigger

        if t["stop_loss"] > 0 and current_ltp <= t["stop_loss"]:
            closed = close_trade(t["id"], current_ltp)
            if closed:
                send_sms_to_all(closed, action="EXIT")
        elif t["target_price"] > 0 and current_ltp >= t["target_price"]:
            closed = close_trade(t["id"], current_ltp)
            if closed:
                send_sms_to_all(closed, action="EXIT")

    # ── KITE-STYLE HEADER ──
    day_change = df["Close"].iloc[-1] - df["Open"].iloc[0]
    day_pct = (day_change / df["Open"].iloc[0]) * 100
    chg_color = "#4caf50" if day_change >= 0 else "#f44336"
    arrow = "▲" if day_change >= 0 else "▼"
    atm_s = _atm_strike(spot_price)
    opt_t = "CE" if signal.get("buy_count", 0) >= signal.get("sell_count", 0) else "PE"

    st.markdown(f"""
    <div style="display:flex;justify-content:space-between;align-items:flex-end;padding:4px 0 10px 0;border-bottom:1px solid #2a2a4a;margin-bottom:10px;">
        <div>
            <span style="color:#e8e8e8;font-size:1.6em;font-weight:700;">{selected_symbol}</span>
            <span style="color:#6b7280;font-size:0.85em;margin-left:8px;">NSE</span>
            <div style="margin-top:2px;">
                <span style="color:#e8e8e8;font-size:1.3em;font-weight:600;">₹{spot_price:,.2f}</span>
                <span style="color:{chg_color};font-size:0.9em;font-weight:500;margin-left:10px;">{arrow} {abs(day_change):,.2f} ({day_pct:+.2f}%)</span>
            </div>
        </div>
        <div style="text-align:right;">
            <div style="color:#6b7280;font-size:0.72em;text-transform:uppercase;">ATM Option</div>
            <div style="color:#e8e8e8;font-size:1.1em;font-weight:600;">{atm_s} {opt_t}</div>
            <div style="display:flex;gap:16px;margin-top:2px;">
                <span style="color:#6b7280;font-size:0.78em;">O: ₹{df['Open'].iloc[0]:,.2f}</span>
                <span style="color:#6b7280;font-size:0.78em;">H: ₹{df['High'].max():,.2f}</span>
                <span style="color:#6b7280;font-size:0.78em;">L: ₹{df['Low'].min():,.2f}</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if sms_sent_this_run:
        st.success(f"Signal fired: {action} {selected_symbol} — SMS sent to {sms_sent_count}")
    elif action in ("BUY", "SELL") and not cooldown_ok:
        remaining = 900 - int((datetime.now(IST) - last_signal_time).total_seconds())
        st.caption(f"⏳ {action} signal on cooldown ({remaining // 60}m {remaining % 60}s)")
    elif action in ("BUY", "SELL"):
        st.caption(f"📱 {action} signal sent — waiting for next")
    else:
        st.markdown(f'<div class="auto-sms-banner"><div class="title">Scanning · {len(subs)} subscriber(s)</div><div class="info">Auto-detects signals → picks option → sends SMS</div></div>', unsafe_allow_html=True)

else:
    # Data fetch failed — show warning but DON'T stop the app
    st.warning(f"⚠️ Could not fetch market data for {selected_symbol}. Will retry on next auto-refresh (60s). SMS Admin still works below.")
    action = "HOLD"


# ══════════════════════════════════════════
#  TABS: Signals | Chart | Option Chain | News & AI | SMS Admin
# ══════════════════════════════════════════

tab_signals, tab_chart, tab_optchain, tab_news, tab_sms = st.tabs([
    "📊 Signals", "📈 Chart", "🔗 Option Chain", "📰 News & AI", "📱 SMS Admin"
])


# ── TAB 1: SIGNALS (no chart here anymore) ──
with tab_signals:
    if not data_ok:
        st.error(f"⚠️ Market data unavailable for {selected_symbol}. Auto-retrying every 60s. SMS Admin tab still works.")
    else:
        action_col, chat_col = st.columns([3, 2])

        with action_col:
            if action == "BUY":
                panel_css = "action-buy"
                icon_str = "🟢 BUY"
                if option_rec:
                    avg_price = option_rec.get("premium_avg", round(option_rec["ltp"] * 0.7, 2))
                    steps_html = f'<div class="step">📌 Auto-picked: <b>{option_rec["contract"]}</b></div>'
                    steps_html += f'<div class="step">💰 Entry: <b>₹{option_rec["ltp"]:,.2f}</b></div>'
                    steps_html += f'<div class="step">🎯 Target: <b>₹{option_rec["premium_target"]:,.2f}</b></div>'
                    steps_html += f'<div class="step">📉 Average at: <b>₹{avg_price:,.2f}</b></div>'
                    steps_html += f'<div class="step">📱 SMS sent automatically</div>'
                else:
                    steps_html = f'<div class="step">📌 {selected_symbol} — Buy <b>CE (Call)</b> ATM strike near ₹{spot_price:,.0f}</div>'
                    steps_html += f'<div class="step">💰 Entry: <b>₹{spot_price:,.2f}</b></div>'
                    steps_html += f'<div class="step">🎯 Target: <b>₹{signal["target"]:,.2f}</b></div>'
                    steps_html += f'<div class="step">📉 Average at: <b>₹{round(spot_price * 0.7, 2):,.2f}</b></div>'
                    steps_html += f'<div class="step">📱 SMS sent automatically</div>'
            elif action == "SELL":
                panel_css = "action-sell"
                icon_str = "🔴 SELL"
                if option_rec:
                    avg_price = option_rec.get("premium_avg", round(option_rec["ltp"] * 0.7, 2))
                    steps_html = f'<div class="step">📌 Auto-picked: <b>{option_rec["contract"]}</b></div>'
                    steps_html += f'<div class="step">💰 Entry: <b>₹{option_rec["ltp"]:,.2f}</b></div>'
                    steps_html += f'<div class="step">🎯 Target: <b>₹{option_rec["premium_target"]:,.2f}</b></div>'
                    steps_html += f'<div class="step">📉 Average at: <b>₹{avg_price:,.2f}</b></div>'
                    steps_html += f'<div class="step">📱 SMS sent automatically</div>'
                else:
                    steps_html = f'<div class="step">📌 {selected_symbol} — Buy <b>PE (Put)</b> ATM strike near ₹{spot_price:,.0f}</div>'
                    steps_html += f'<div class="step">💰 Entry: <b>₹{spot_price:,.2f}</b></div>'
                    steps_html += f'<div class="step">🎯 Target: <b>₹{signal["target"]:,.2f}</b></div>'
                    steps_html += f'<div class="step">📉 Average at: <b>₹{round(spot_price * 0.7, 2):,.2f}</b></div>'
                    steps_html += f'<div class="step">📱 SMS sent automatically</div>'
            else:
                panel_css = "action-hold"
                icon_str = "🟡 HOLD"
                steps_html = '<div class="step">⏸️ No clear signal. <b>Waiting for next one...</b></div>'
                steps_html += f'<div class="step">💡 {signal["buy_count"]} BUY / {signal["sell_count"]} SELL indicators — need 3+ to align</div>'
                steps_html += '<div class="step">🤖 App is scanning every 60s. SMS fires automatically.</div>'

            alert_class = ' alert-banner' if action in ("BUY", "SELL") else ''
            panel_html = f'<div class="action-panel {panel_css}{alert_class}"><h2>{icon_str} {selected_symbol}</h2>{steps_html}</div>'
            st.markdown(panel_html, unsafe_allow_html=True)

            if option_rec:
                opt_avg = option_rec.get("premium_avg", round(option_rec["ltp"] * 0.7, 2))
                opt_html = f'<div class="option-card"><h3>📋 Option Contract (Auto-Selected)</h3>'
                opt_html += f'<div class="contract">{option_rec["contract"]}</div>'
                opt_html += f'<div class="detail">Expiry: <b>{option_rec["expiry"]}</b></div>'
                opt_html += f'<div class="detail">Premium: <b>₹{option_rec["ltp"]:,.2f}</b> | Bid: ₹{option_rec["bid"]:,.2f} Ask: ₹{option_rec["ask"]:,.2f}</div>'
                opt_html += f'<div class="detail">Lot: <b>{option_rec["lot_size"]}</b> | Total: <b>₹{option_rec["total_premium"]:,.2f}</b></div>'
                opt_html += f'<div class="detail">OI: {option_rec["oi"]:,} | OI Δ: {option_rec["oi_change"]:,} | IV: {option_rec["iv"]}%</div>'
                opt_html += f'<div class="detail" style="margin-top:8px;font-weight:700;">💰 Entry: ₹{option_rec["ltp"]:,.2f} | 🎯 Target: ₹{option_rec["premium_target"]:,.2f} | 📉 Avg: ₹{opt_avg:,.2f}</div>'
                opt_html += '</div>'
                st.markdown(opt_html, unsafe_allow_html=True)

        with chat_col:
            st.markdown(f"### 💬 {selected_symbol} Signal Feed")
            chat_html = '<div class="chat-container">'
            now_str = datetime.now(IST).strftime("%I:%M %p")
            chat_css = f"chat-{action.lower()}"

            # Current signal — show option details if available
            if action in ("BUY", "SELL") and option_rec:
                opt_type = "CE" if action == "BUY" else "PE"
                avg_p = option_rec.get("premium_avg", round(option_rec["ltp"] * 0.7, 2))
                chat_text = f'{"🟢" if action=="BUY" else "🔴"} <b>{action} {selected_symbol} {int(option_rec["strike"])}{opt_type}</b>'
                chat_text += f'<br>💰 Entry: <b>₹{option_rec["ltp"]:,.2f}</b>'
                chat_text += f'<br>🎯 Target: <b>₹{option_rec["premium_target"]:,.2f}</b>'
                chat_text += f'<br>📉 Avg: <b>₹{avg_p:,.2f}</b>'
                chat_text += f'<br>📱 SMS sent automatically'
            elif action in ("BUY", "SELL"):
                opt_type = "CE" if action == "BUY" else "PE"
                atm_s = _atm_strike(spot_price)
                avg_spot = round(spot_price * 0.7, 2)
                chat_text = f'{"🟢" if action=="BUY" else "🔴"} <b>{action} {selected_symbol} {atm_s}{opt_type}</b>'
                chat_text += f'<br>💰 Entry: <b>₹{spot_price:,.2f}</b>'
                chat_text += f'<br>🎯 Target: <b>₹{signal["target"]:,.2f}</b>' if signal.get("target") else ''
                chat_text += f'<br>📉 Avg: <b>₹{avg_spot:,.2f}</b>'
                chat_text += f'<br>📱 SMS sent automatically'
            else:
                chat_text = f'🟡 <b>HOLD — {selected_symbol}</b><br>⏸️ No clear signal. Scanning...'
                chat_text += f'<br>💡 {signal["buy_count"]} BUY / {signal["sell_count"]} SELL indicators'
            chat_html += f'<div class="chat-msg {chat_css}">{chat_text}<div class="chat-time">{now_str} ✓✓</div></div>'

            # Historical signals — show only last 2
            for s in reversed(all_signals[-2:]):
                ts = s["index"].strftime("%I:%M %p, %d %b") if hasattr(s["index"], "strftime") else str(s["index"])
                s_css = "chat-buy" if s["action"] == "BUY" else "chat-sell"
                opt_type = "CE" if s["action"] == "BUY" else "PE"
                s_icon = "🟢" if s["action"] == "BUY" else "🔴"
                atm = _atm_strike(s["price"])
                s_avg = round(s["price"] * 0.7, 2)
                chat_html += f'<div class="chat-msg {s_css}">{s_icon} <b>{s["action"]} {selected_symbol} {atm}{opt_type}</b><br>💰 Entry: ₹{s["price"]:,.2f} &nbsp; 🎯 T: ₹{s["target"]:,.2f} &nbsp; 📉 Avg: ₹{s_avg:,.2f}<div class="chat-time">{ts}</div></div>'
            chat_html += '</div>'
            st.markdown(chat_html, unsafe_allow_html=True)

        st.markdown("---")

        # ── Indicator Cards ──
        def badge(sig):
            c = {"BUY": "buy", "SELL": "sell", "NEUTRAL": "neutral"}.get(sig, "neutral")
            return f'<span class="badge badge-{c}">{sig}</span>'

        ic1, ic2, ic3, ic4, ic5 = st.columns(5)
        with ic1:
            rl = "Oversold" if rsi["value"] < 30 else "Overbought" if rsi["value"] > 70 else "Neutral"
            st.markdown(f'<div class="indicator-card"><h4>RSI ({RSI_PERIOD})</h4><div class="value">{rsi["value"]}</div>{badge(rsi["signal"])}<div style="color:#9ca3af;font-size:0.7em;margin-top:4px;">{rl}</div></div>', unsafe_allow_html=True)
        with ic2:
            st.markdown(f'<div class="indicator-card"><h4>MACD</h4><div class="value">{macd_data["histogram"]}</div>{badge(macd_data["signal"])}<div style="color:#9ca3af;font-size:0.7em;margin-top:4px;">L:{macd_data["macd_line"]} S:{macd_data["signal_line"]}</div></div>', unsafe_allow_html=True)
        with ic3:
            dl = "▲ Up" if supertrend["direction"] == 1 else "▼ Down"
            st.markdown(f'<div class="indicator-card"><h4>SuperTrend</h4><div class="value">{dl}</div>{badge(supertrend["signal"])}<div style="color:#9ca3af;font-size:0.7em;margin-top:4px;">₹{supertrend["value"]:,.2f}</div></div>', unsafe_allow_html=True)
        with ic4:
            vd = vwap_data["current_price"] - vwap_data["value"]
            st.markdown(f'<div class="indicator-card"><h4>VWAP</h4><div class="value">₹{vwap_data["value"]:,.2f}</div>{badge(vwap_data["signal"])}<div style="color:#9ca3af;font-size:0.7em;margin-top:4px;">{"Above" if vd > 0 else "Below"} by ₹{abs(vd):,.2f}</div></div>', unsafe_allow_html=True)
        with ic5:
            st.markdown(f'<div class="indicator-card"><h4>OI / PCR</h4><div class="value">{oi_data["pcr"]}</div>{badge(oi_data["signal"])}<div style="color:#9ca3af;font-size:0.7em;margin-top:4px;">Net Δ: {oi_data["net_oi_change"]:,}</div></div>', unsafe_allow_html=True)

        # ── Signal History Table ──
        if all_signals:
            st.markdown(f"#### 📋 {selected_symbol} Signal History")
            rows = ""
            for s in reversed(all_signals[-8:]):
                ts = s["index"].strftime("%d %b %H:%M") if hasattr(s["index"], "strftime") else str(s["index"])
                ac = "#26a69a" if s["action"] == "BUY" else "#ef5350"
                opt_type = "CE" if s["action"] == "BUY" else "PE"
                atm = _atm_strike(s["price"])
                contract = f"{selected_symbol} {atm}{opt_type}"
                rows += f'<tr><td>{ts}</td><td><span style="color:{ac};font-weight:700;">{"▲" if s["action"]=="BUY" else "▼"} {s["action"]}</span></td><td>{contract}</td><td>₹{s["price"]:,.2f}</td><td>₹{s["target"]:,.2f}</td></tr>'
            st.markdown(f'<table class="signal-table"><thead><tr><th>Time</th><th>Signal</th><th>Contract</th><th>Entry</th><th>Target</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)


# ── TAB 2: CHART (Candlestick with Support/Resistance) ──
with tab_chart:
    if data_ok and not df.empty:
        sr = compute_support_resistance(df)

        # Support/Resistance cards at top
        sr_html = '<div style="display:flex;gap:8px;margin-bottom:12px;justify-content:center;">'
        sr_html += f'<div style="background:#7f1d1d;padding:8px 16px;border-radius:8px;text-align:center;"><span style="color:#94a3b8;font-size:0.7em;">S2</span><br><span style="color:#ef4444;font-weight:700;">₹{sr["s2"]:,.2f}</span></div>'
        sr_html += f'<div style="background:#991b1b;padding:8px 16px;border-radius:8px;text-align:center;"><span style="color:#94a3b8;font-size:0.7em;">S1</span><br><span style="color:#f87171;font-weight:700;">₹{sr["s1"]:,.2f}</span></div>'
        sr_html += f'<div style="background:#1e293b;padding:8px 16px;border-radius:8px;text-align:center;border:2px solid #6366f1;"><span style="color:#94a3b8;font-size:0.7em;">PIVOT</span><br><span style="color:#a5b4fc;font-weight:700;">₹{sr["pivot"]:,.2f}</span></div>'
        sr_html += f'<div style="background:#064e3b;padding:8px 16px;border-radius:8px;text-align:center;"><span style="color:#94a3b8;font-size:0.7em;">R1</span><br><span style="color:#34d399;font-weight:700;">₹{sr["r1"]:,.2f}</span></div>'
        sr_html += f'<div style="background:#065f46;padding:8px 16px;border-radius:8px;text-align:center;"><span style="color:#94a3b8;font-size:0.7em;">R2</span><br><span style="color:#22c55e;font-weight:700;">₹{sr["r2"]:,.2f}</span></div>'
        sr_html += '</div>'
        st.markdown(sr_html, unsafe_allow_html=True)

        # Build candlestick data from yfinance DataFrame
        candle_data = []
        vol_data = []
        for idx, row in df.iterrows():
            ts = int(idx.timestamp()) if hasattr(idx, 'timestamp') else 0
            candle_data.append({
                "time": ts,
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
            })
            vol_data.append({
                "time": ts,
                "value": int(row["Volume"]) if "Volume" in row else 0,
                "color": "rgba(38,166,154,0.4)" if row["Close"] >= row["Open"] else "rgba(239,83,80,0.4)",
            })

        candle_json = json.dumps(candle_data)
        vol_json = json.dumps(vol_data)

        # BUY/SELL markers — only last 2 to keep chart clean
        markers = []
        for s in all_signals[-2:]:
            sig_ts = int(s["index"].timestamp()) if hasattr(s["index"], "timestamp") else 0
            if s["action"] == "BUY":
                markers.append({
                    "time": sig_ts,
                    "position": "belowBar",
                    "color": "#26a69a",
                    "shape": "arrowUp",
                    "text": "BUY",
                })
            elif s["action"] == "SELL":
                markers.append({
                    "time": sig_ts,
                    "position": "aboveBar",
                    "color": "#ef5350",
                    "shape": "arrowDown",
                    "text": "SELL",
                })
        markers_json = json.dumps(markers)

        last_price = round(float(df["Close"].iloc[-1]), 2)
        day_chg_pct = round(float((df["Close"].iloc[-1] - df["Open"].iloc[0]) / df["Open"].iloc[0] * 100), 2)
        price_color = "#26a69a" if day_chg_pct >= 0 else "#ef5350"

        chart_html = f"""
        <div style="position:relative;">
            <div id="chart_header" style="display:flex;justify-content:space-between;align-items:center;padding:8px 16px;background:#131722;border-radius:10px 10px 0 0;border-bottom:1px solid #1e293b;">
                <div>
                    <span style="color:#e5e7eb;font-weight:700;font-size:1.1em;">{selected_symbol}</span>
                    <span style="color:{price_color};font-weight:600;margin-left:12px;">₹{last_price:,.2f}</span>
                    <span style="color:{price_color};font-size:0.85em;margin-left:6px;">({'+' if day_chg_pct >= 0 else ''}{day_chg_pct}%)</span>
                </div>
                <div style="display:flex;gap:16px;align-items:center;font-size:0.75em;">
                    <span><span style="color:#a5b4fc;">━</span> Pivot</span>
                    <span><span style="color:#34d399;">┅</span> R1/R2</span>
                    <span><span style="color:#f87171;">┅</span> S1/S2</span>
                    <button id="chart_reset_btn" style="background:#2a2e39;border:1px solid #3a3e49;color:#e5e7eb;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:1em;display:flex;align-items:center;gap:4px;" title="Reset to current">↻ Reset</button>
                </div>
            </div>
            <div id="chart_container" style="width:100%;height:520px;background:#131722;border-radius:0 0 10px 10px;overflow:hidden;"></div>
        </div>
        <script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
        <script>
        (function() {{
            var container = document.getElementById('chart_container');
            var chart = LightweightCharts.createChart(container, {{
                width: container.clientWidth,
                height: 520,
                layout: {{
                    background: {{ type: 'solid', color: '#131722' }},
                    textColor: '#9ca3af',
                    fontSize: 11,
                }},
                grid: {{
                    vertLines: {{ color: 'rgba(42,46,57,0.5)' }},
                    horzLines: {{ color: 'rgba(42,46,57,0.5)' }},
                }},
                crosshair: {{
                    mode: LightweightCharts.CrosshairMode.Normal,
                    vertLine: {{ color: 'rgba(99,102,241,0.4)', width: 1, style: 2 }},
                    horzLine: {{ color: 'rgba(99,102,241,0.4)', width: 1, style: 2 }},
                }},
                rightPriceScale: {{
                    borderColor: '#2a2e39',
                    scaleMargins: {{ top: 0.05, bottom: 0.2 }},
                }},
                timeScale: {{
                    borderColor: '#2a2e39',
                    timeVisible: true,
                    secondsVisible: false,
                    rightOffset: 5,
                    barSpacing: 8,
                }},
                watermark: {{
                    visible: true,
                    text: '{selected_symbol}',
                    color: 'rgba(99,102,241,0.08)',
                    fontSize: 48,
                }},
            }});

            // Candlesticks
            var candleSeries = chart.addCandlestickSeries({{
                upColor: '#26a69a', downColor: '#ef5350',
                borderUpColor: '#26a69a', borderDownColor: '#ef5350',
                wickUpColor: '#26a69a', wickDownColor: '#ef5350',
            }});
            candleSeries.setData({candle_json});

            // Current price line
            candleSeries.createPriceLine({{
                price: {last_price}, color: '{price_color}',
                lineWidth: 1, lineStyle: 0,
                axisLabelVisible: true, title: '',
            }});

            // Support/Resistance lines
            candleSeries.createPriceLine({{ price: {sr["r2"]}, color: '#22c55e', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'R2' }});
            candleSeries.createPriceLine({{ price: {sr["r1"]}, color: '#34d399', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'R1' }});
            candleSeries.createPriceLine({{ price: {sr["pivot"]}, color: '#a5b4fc', lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title: 'Pivot' }});
            candleSeries.createPriceLine({{ price: {sr["s1"]}, color: '#f87171', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'S1' }});
            candleSeries.createPriceLine({{ price: {sr["s2"]}, color: '#ef4444', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'S2' }});

            // BUY/SELL markers
            var markers = {markers_json};
            if (markers.length > 0) {{ candleSeries.setMarkers(markers); }}

            // Volume with gradient colors
            var volSeries = chart.addHistogramSeries({{
                priceFormat: {{ type: 'volume' }},
                priceScaleId: 'vol',
            }});
            volSeries.priceScale().applyOptions({{
                scaleMargins: {{ top: 0.82, bottom: 0 }},
            }});
            volSeries.setData({vol_json});

            chart.timeScale().fitContent();
            new ResizeObserver(function() {{
                chart.applyOptions({{ width: container.clientWidth }});
            }}).observe(container);

            // Reset button — snap chart back to fit all content
            document.getElementById('chart_reset_btn').addEventListener('click', function() {{
                chart.timeScale().fitContent();
            }});
        }})();
        </script>
        """
        components.html(chart_html, height=570, scrolling=False)
    else:
        st.warning("Chart unavailable — market data not loaded. Will retry on next refresh.")


# ── TAB 3: OPTION CHAIN (Dhan API → NSE fallback) ──
with tab_optchain:
    nse_sym = sym.get("nse", "")
    st.markdown(f"### 🔗 Option Chain — {selected_symbol}" + (f" ({nse_sym})" if nse_sym else ""))

    @st.cache_data(ttl=120)
    def fetch_option_chain_dhan(symbol_name):
        """Try Dhan API first, fall back to nsepython."""
        try:
            oc = get_option_chain_for_symbol(symbol_name)
            if oc and oc.get("raw"):
                return {"source": "dhan", "data": oc}
        except Exception as e:
            print(f"[OC] Dhan failed: {e}")

        # Fallback to nsepython
        nse_s = SYMBOLS.get(symbol_name, {}).get("nse", symbol_name)
        if nse_s:
            try:
                from nsepython import option_chain
                data = option_chain(nse_s)
                if data and "records" in data:
                    return {"source": "nse", "data": data}
            except Exception:
                pass
        return None

    with st.spinner("Loading option chain..."):
        oc_result = fetch_option_chain_dhan(selected_symbol)

    if oc_result is None:
        st.warning("Could not fetch option chain data. Will retry on next refresh.")
    elif oc_result["source"] == "dhan":
        # ── DHAN OPTION CHAIN ──
        dhan_oc = oc_result["data"]
        raw = dhan_oc["raw"]
        spot_for_oc = raw.get("last_price", 0) or (spot_price if data_ok else 0)
        expiry_list = dhan_oc.get("expiry_list", [])
        current_expiry = dhan_oc.get("expiry", "")

        if expiry_list:
            selected_expiry = st.selectbox("Select Expiry", expiry_list, index=expiry_list.index(current_expiry) if current_expiry in expiry_list else 0, key="oc_expiry_dhan")
            # Re-fetch if different expiry selected
            if selected_expiry != current_expiry:
                try:
                    idx_id = None
                    sym_upper = selected_symbol.strip().upper()
                    from dhan_api import get_index_security_id, get_security_id
                    idx_id = get_index_security_id(sym_upper)
                    if idx_id:
                        new_oc = get_option_chain_dhan(idx_id, "IDX_I", selected_expiry)
                    else:
                        sec_id = get_security_id(sym.get("nse", sym_upper), "NSE_EQ")
                        if sec_id:
                            new_oc = get_option_chain_dhan(sec_id, "NSE_EQ", selected_expiry)
                        else:
                            new_oc = raw
                    if new_oc:
                        raw = new_oc
                        spot_for_oc = raw.get("last_price", spot_for_oc)
                except Exception:
                    pass
        else:
            selected_expiry = current_expiry

        # Parse Dhan option chain format
        oc_strikes = raw.get("oc", {})
        if oc_strikes:
            chain_rows = []
            all_strikes = set()
            for strike_str, strike_data in oc_strikes.items():
                try:
                    strike_val = float(strike_str)
                except ValueError:
                    continue
                all_strikes.add(strike_val)
                ce = strike_data.get("ce", strike_data.get("CE", {}))
                pe = strike_data.get("pe", strike_data.get("PE", {}))
                chain_rows.append({
                    "strike": strike_val,
                    "ce_oi": ce.get("oi", 0),
                    "ce_oi_chg": ce.get("oi", 0) - ce.get("previous_oi", 0),
                    "ce_vol": ce.get("volume", 0),
                    "ce_iv": ce.get("implied_volatility", 0),
                    "ce_ltp": ce.get("last_price", 0),
                    "pe_ltp": pe.get("last_price", 0),
                    "pe_iv": pe.get("implied_volatility", 0),
                    "pe_vol": pe.get("volume", 0),
                    "pe_oi_chg": pe.get("oi", 0) - pe.get("previous_oi", 0),
                    "pe_oi": pe.get("oi", 0),
                })

            chain_rows.sort(key=lambda r: r["strike"])
            atm_strike = min(all_strikes, key=lambda s: abs(s - spot_for_oc)) if all_strikes and spot_for_oc > 0 else 0

            if atm_strike > 0:
                sorted_strikes = sorted(all_strikes)
                atm_idx = sorted_strikes.index(atm_strike) if atm_strike in sorted_strikes else len(sorted_strikes) // 2
                visible_strikes = set(sorted_strikes[max(0, atm_idx - 10):atm_idx + 11])
                chain_rows = [r for r in chain_rows if r["strike"] in visible_strikes]

            if chain_rows:
                oc_table = '<table style="width:100%;border-collapse:collapse;font-size:0.82em;text-align:center;">'
                oc_table += '<thead><tr style="background:#1e293b;">'
                oc_table += '<th style="padding:6px;color:#22c55e;">OI</th><th style="padding:6px;color:#22c55e;">OI Chg</th><th style="padding:6px;color:#22c55e;">Volume</th><th style="padding:6px;color:#22c55e;">IV</th><th style="padding:6px;color:#22c55e;">LTP</th>'
                oc_table += '<th style="padding:6px;color:#fbbf24;font-weight:700;">STRIKE</th>'
                oc_table += '<th style="padding:6px;color:#ef4444;">LTP</th><th style="padding:6px;color:#ef4444;">IV</th><th style="padding:6px;color:#ef4444;">Volume</th><th style="padding:6px;color:#ef4444;">OI Chg</th><th style="padding:6px;color:#ef4444;">OI</th>'
                oc_table += '</tr>'
                oc_table += '<tr style="background:#1e293b;"><th colspan="5" style="padding:4px;color:#22c55e;font-size:0.9em;">CALLS</th><th></th><th colspan="5" style="padding:4px;color:#ef4444;font-size:0.9em;">PUTS</th></tr>'
                oc_table += '</thead><tbody>'

                for r in chain_rows:
                    is_atm = r["strike"] == atm_strike
                    is_itm_ce = spot_for_oc > 0 and r["strike"] < spot_for_oc
                    is_itm_pe = spot_for_oc > 0 and r["strike"] > spot_for_oc
                    row_border = "border:2px solid #fbbf24;" if is_atm else ""
                    ce_bg = "background:rgba(34,197,94,0.08);" if is_itm_ce else ""
                    pe_bg = "background:rgba(239,68,68,0.08);" if is_itm_pe else ""
                    atm_label = " (ATM)" if is_atm else ""

                    oc_table += f'<tr style="{row_border}border-bottom:1px solid #1e293b;">'
                    oc_table += f'<td style="padding:5px;color:#e5e7eb;{ce_bg}">{r["ce_oi"]:,}</td>'
                    oc_table += f'<td style="padding:5px;color:{"#22c55e" if r["ce_oi_chg"]>0 else "#ef4444" if r["ce_oi_chg"]<0 else "#e5e7eb"};{ce_bg}">{r["ce_oi_chg"]:,}</td>'
                    oc_table += f'<td style="padding:5px;color:#e5e7eb;{ce_bg}">{r["ce_vol"]:,}</td>'
                    oc_table += f'<td style="padding:5px;color:#e5e7eb;{ce_bg}">{r["ce_iv"]:.1f}</td>'
                    oc_table += f'<td style="padding:5px;color:#e5e7eb;font-weight:600;{ce_bg}">{r["ce_ltp"]:,.2f}</td>'
                    oc_table += f'<td style="padding:5px;color:#fbbf24;font-weight:700;background:#1a1a2e;">{int(r["strike"]):,}{atm_label}</td>'
                    oc_table += f'<td style="padding:5px;color:#e5e7eb;font-weight:600;{pe_bg}">{r["pe_ltp"]:,.2f}</td>'
                    oc_table += f'<td style="padding:5px;color:#e5e7eb;{pe_bg}">{r["pe_iv"]:.1f}</td>'
                    oc_table += f'<td style="padding:5px;color:#e5e7eb;{pe_bg}">{r["pe_vol"]:,}</td>'
                    oc_table += f'<td style="padding:5px;color:{"#22c55e" if r["pe_oi_chg"]>0 else "#ef4444" if r["pe_oi_chg"]<0 else "#e5e7eb"};{pe_bg}">{r["pe_oi_chg"]:,}</td>'
                    oc_table += f'<td style="padding:5px;color:#e5e7eb;{pe_bg}">{r["pe_oi"]:,}</td>'
                    oc_table += '</tr>'

                oc_table += '</tbody></table>'
                st.markdown(oc_table, unsafe_allow_html=True)
                src_badge = '<span style="background:#6366f1;color:white;padding:2px 8px;border-radius:4px;font-size:0.7em;">Dhan API</span>'
                if spot_for_oc > 0:
                    st.caption(f"Spot: ₹{spot_for_oc:,.2f} | ATM Strike: {int(atm_strike):,} | Expiry: {selected_expiry}")
                st.markdown(f"Data source: {src_badge}", unsafe_allow_html=True)
            else:
                st.info("No option chain rows found for this expiry.")
        else:
            st.warning("Option chain data empty from Dhan API.")

    elif oc_result["source"] == "nse":
        # ── NSE FALLBACK OPTION CHAIN ──
        records = oc_result["data"]["records"]
        expiry_dates = records.get("expiryDates", [])
        spot_for_oc = data_ok and spot_price or 0

        if expiry_dates:
            selected_expiry = st.selectbox("Select Expiry", expiry_dates, index=0, key="oc_expiry")
        else:
            selected_expiry = None

        if selected_expiry:
            chain_rows = []
            all_strikes = set()
            for item in records.get("data", []):
                if item.get("expiryDate") == selected_expiry:
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
                        "ce_ltp": ce.get("lastPrice", 0),
                        "pe_ltp": pe.get("lastPrice", 0),
                        "pe_iv": pe.get("impliedVolatility", 0),
                        "pe_vol": pe.get("totalTradedVolume", 0),
                        "pe_oi_chg": pe.get("changeinOpenInterest", 0),
                        "pe_oi": pe.get("openInterest", 0),
                    })

            chain_rows.sort(key=lambda r: r["strike"])
            atm_strike = min(all_strikes, key=lambda s: abs(s - spot_for_oc)) if all_strikes and spot_for_oc > 0 else 0

            if atm_strike > 0:
                sorted_strikes = sorted(all_strikes)
                atm_idx = sorted_strikes.index(atm_strike) if atm_strike in sorted_strikes else len(sorted_strikes) // 2
                visible_strikes = set(sorted_strikes[max(0, atm_idx - 10):atm_idx + 11])
                chain_rows = [r for r in chain_rows if r["strike"] in visible_strikes]

            if chain_rows:
                oc_table = '<table style="width:100%;border-collapse:collapse;font-size:0.82em;text-align:center;">'
                oc_table += '<thead><tr style="background:#1e293b;">'
                oc_table += '<th style="padding:6px;color:#22c55e;">OI</th><th style="padding:6px;color:#22c55e;">OI Chg</th><th style="padding:6px;color:#22c55e;">Volume</th><th style="padding:6px;color:#22c55e;">IV</th><th style="padding:6px;color:#22c55e;">LTP</th>'
                oc_table += '<th style="padding:6px;color:#fbbf24;font-weight:700;">STRIKE</th>'
                oc_table += '<th style="padding:6px;color:#ef4444;">LTP</th><th style="padding:6px;color:#ef4444;">IV</th><th style="padding:6px;color:#ef4444;">Volume</th><th style="padding:6px;color:#ef4444;">OI Chg</th><th style="padding:6px;color:#ef4444;">OI</th>'
                oc_table += '</tr>'
                oc_table += '<tr style="background:#1e293b;"><th colspan="5" style="padding:4px;color:#22c55e;font-size:0.9em;">CALLS</th><th></th><th colspan="5" style="padding:4px;color:#ef4444;font-size:0.9em;">PUTS</th></tr>'
                oc_table += '</thead><tbody>'

                for r in chain_rows:
                    is_atm = r["strike"] == atm_strike
                    is_itm_ce = spot_for_oc > 0 and r["strike"] < spot_for_oc
                    is_itm_pe = spot_for_oc > 0 and r["strike"] > spot_for_oc
                    row_border = "border:2px solid #fbbf24;" if is_atm else ""
                    ce_bg = "background:rgba(34,197,94,0.08);" if is_itm_ce else ""
                    pe_bg = "background:rgba(239,68,68,0.08);" if is_itm_pe else ""
                    atm_label = " (ATM)" if is_atm else ""

                    oc_table += f'<tr style="{row_border}border-bottom:1px solid #1e293b;">'
                    oc_table += f'<td style="padding:5px;color:#e5e7eb;{ce_bg}">{r["ce_oi"]:,}</td>'
                    oc_table += f'<td style="padding:5px;color:{"#22c55e" if r["ce_oi_chg"]>0 else "#ef4444" if r["ce_oi_chg"]<0 else "#e5e7eb"};{ce_bg}">{r["ce_oi_chg"]:,}</td>'
                    oc_table += f'<td style="padding:5px;color:#e5e7eb;{ce_bg}">{r["ce_vol"]:,}</td>'
                    oc_table += f'<td style="padding:5px;color:#e5e7eb;{ce_bg}">{r["ce_iv"]:.1f}</td>'
                    oc_table += f'<td style="padding:5px;color:#e5e7eb;font-weight:600;{ce_bg}">{r["ce_ltp"]:,.2f}</td>'
                    oc_table += f'<td style="padding:5px;color:#fbbf24;font-weight:700;background:#1a1a2e;">{int(r["strike"]):,}{atm_label}</td>'
                    oc_table += f'<td style="padding:5px;color:#e5e7eb;font-weight:600;{pe_bg}">{r["pe_ltp"]:,.2f}</td>'
                    oc_table += f'<td style="padding:5px;color:#e5e7eb;{pe_bg}">{r["pe_iv"]:.1f}</td>'
                    oc_table += f'<td style="padding:5px;color:#e5e7eb;{pe_bg}">{r["pe_vol"]:,}</td>'
                    oc_table += f'<td style="padding:5px;color:{"#22c55e" if r["pe_oi_chg"]>0 else "#ef4444" if r["pe_oi_chg"]<0 else "#e5e7eb"};{pe_bg}">{r["pe_oi_chg"]:,}</td>'
                    oc_table += f'<td style="padding:5px;color:#e5e7eb;{pe_bg}">{r["pe_oi"]:,}</td>'
                    oc_table += '</tr>'

                oc_table += '</tbody></table>'
                st.markdown(oc_table, unsafe_allow_html=True)
                src_badge = '<span style="background:#f59e0b;color:black;padding:2px 8px;border-radius:4px;font-size:0.7em;">NSE</span>'
                if spot_for_oc > 0:
                    st.caption(f"Spot: ₹{spot_for_oc:,.2f} | ATM Strike: {int(atm_strike):,} | Expiry: {selected_expiry}")
                st.markdown(f"Data source: {src_badge}", unsafe_allow_html=True)
            else:
                st.info("No option chain rows found for this expiry.")






# ── TAB 4: NEWS + AI ──
with tab_news:
    nc, ac_col = st.columns([3, 2])
    with nc:
        st.markdown("### 📰 Market News")
        if news:
            for a in news:
                s = a.get("sentiment", "NEUTRAL").lower()
                h = a.get("headline", "")
                u = a.get("url", "")
                src = a.get("source", "")
                lnk = f' · <a href="{u}" target="_blank" style="color:#60a5fa;">Read →</a>' if u else ""
                st.markdown(f'<div class="news-item {s}"><span class="badge badge-{s}">{s.upper()}</span> <strong>{h}</strong><br><small style="color:#9ca3af;">{src}{lnk}</small></div>', unsafe_allow_html=True)
        else:
            st.info("No news available.")

    with ac_col:
        st.markdown("### 🤖 Claude Analysis")
        if data_ok:
            prices_dict = {
                "nifty": inst_data["spot"] if sym["nse"] == "NIFTY" else None,
                "banknifty": inst_data["spot"] if sym["nse"] == "BANKNIFTY" else None,
            }
            with st.spinner("AI analyzing..."):
                try:
                    analysis = analyze_market(
                        prices_dict, signal, rsi, macd_data,
                        supertrend, vwap_data, oi_data, news,
                    )
                except Exception:
                    analysis = "Analysis unavailable — will retry on next refresh."
            st.markdown(f'<div class="analysis-box"><p style="color:#e5e7eb;line-height:1.7;font-size:0.95em;">{analysis}</p></div>', unsafe_allow_html=True)
        else:
            st.info("Market data unavailable — AI analysis will appear when data loads.")


# ── TAB 5: SMS ADMIN ──
with tab_sms:
    sms_col1, sms_col2 = st.columns([1, 1])

    with sms_col1:
        st.markdown("### 📱 Subscriber Management")

        st.markdown("##### Add Subscriber")
        sub_phone = st.text_input("Phone Number", placeholder="+91XXXXXXXXXX or 9876543210", key="add_phone")
        sub_name = st.text_input("Name (optional)", placeholder="e.g. Rahul", key="add_name")
        if st.button("➕ Add Subscriber", use_container_width=True):
            if sub_phone.strip():
                ok = add_subscriber(sub_phone, sub_name)
                if ok:
                    st.success(f"Added {sub_phone}")
                    st.rerun()
                else:
                    st.warning("Already exists or invalid number")
            else:
                st.error("Enter a phone number")

        st.markdown("##### Current Subscribers")
        subs_list = get_subscribers()
        if subs_list:
            sub_rows = ""
            for s in subs_list:
                status = "🟢 Active" if s.get("active", True) else "🔴 Inactive"
                sub_rows += f'<tr><td>{s.get("name", "-")}</td><td>{s["phone"]}</td><td>{status}</td><td>{s.get("added", "")[:10]}</td></tr>'
            st.markdown(f'<table class="sub-table"><thead><tr><th>Name</th><th>Phone</th><th>Status</th><th>Added</th></tr></thead><tbody>{sub_rows}</tbody></table>', unsafe_allow_html=True)

            st.markdown("##### Remove Subscriber")
            remove_phone = st.text_input("Phone to remove", placeholder="+91XXXXXXXXXX", key="remove_phone")
            if st.button("🗑️ Remove", use_container_width=True):
                if remove_phone.strip():
                    ok = remove_subscriber(remove_phone)
                    if ok:
                        st.success(f"Removed {remove_phone}")
                        st.rerun()
                    else:
                        st.warning("Number not found")
        else:
            st.info("No subscribers yet. Add phone numbers above to receive auto SMS alerts.")

    with sms_col2:
        st.markdown("### 📋 SMS Delivery Log")
        sms_log = get_sms_log()
        if sms_log:
            log_rows = ""
            for entry in reversed(sms_log[-25:]):
                status_color = "#22c55e" if entry.get("status") != "failed" else "#ef4444"
                ts = entry.get("timestamp", "")[:16]
                phone = entry.get("phone", "")
                msg = entry.get("message", "")[:60]
                status = entry.get("status", "unknown")
                log_rows += f'<tr><td>{ts}</td><td>{phone}</td><td style="color:{status_color};font-weight:600;">{status}</td><td title="{entry.get("message", "")}">{msg}...</td></tr>'
            st.markdown(f'<table class="sms-log-table"><thead><tr><th>Time</th><th>Phone</th><th>Status</th><th>Message</th></tr></thead><tbody>{log_rows}</tbody></table>', unsafe_allow_html=True)
        else:
            st.info("No SMS sent yet. When a signal fires, SMS goes out automatically.")

        st.markdown("##### 🧪 Send Test SMS")
        if st.button("📤 Send Test to All Subscribers", use_container_width=True):
            _spot = spot_price if data_ok else 23000
            _strike = str(round(_spot / 100) * 100)
            test_trade = {
                "instrument": selected_symbol,
                "strike": _strike,
                "option_type": "CE",
                "expiry": "Weekly",
                "entry_price": 125,
                "target_price": 145,
                "stop_loss": 95,
                "quantity": 1,
            }
            results = send_sms_to_all(test_trade, action="BUY")
            if results:
                sent = sum(1 for r in results if r["status"] != "failed")
                failed = sum(1 for r in results if r["status"] == "failed")
                if sent > 0:
                    st.success(f"Test SMS delivered to {sent} subscriber(s)")
                elif failed > 0:
                    err = results[0].get("api_response", results[0].get("error", "unknown"))
                    st.error(f"SMS attempted to {failed} subscriber(s) but failed: {err}")
                else:
                    st.warning(f"SMS sent to {len(results)} subscriber(s) — check log for status")
            else:
                st.info("No subscribers to send to.")


st.markdown("---")
st.caption("⚠️ For educational purposes only. Not financial advice. Always use stop loss. App auto-refreshes every 60s during market hours.")
