import streamlit as st
import streamlit.components.v1 as components
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
    get_option_recommendation, is_market_open,
)
from indicators import (
    compute_rsi, compute_macd, compute_supertrend, compute_vwap,
    evaluate_oi, generate_signal, compute_all_signals,
)
from news_scraper import scrape_moneycontrol_news
from claude_analyzer import analyze_market
from notifier import format_signal_chat, send_signal_email
from trades import (
    create_trade, close_trade, get_open_trades, get_closed_trades,
    format_trade_display, delete_trade,
)
from sms_sender import (
    send_sms_to_all, get_subscribers, add_subscriber,
    remove_subscriber, get_sms_log,
)

IST = pytz.timezone("Asia/Kolkata")

# ── All F&O eligible instruments (searchable) ──
FNO_INSTRUMENTS = {
    # Indices
    "NIFTY 50": "NIFTY", "BANK NIFTY": "BANKNIFTY", "FIN NIFTY": "FINNIFTY",
    "MIDCAP NIFTY": "MIDCPNIFTY", "SENSEX": "SENSEX", "BANKEX": "BANKEX",
    # F&O Stocks (NSE)
    "RELIANCE": "RELIANCE", "HDFC BANK": "HDFCBANK", "ICICI BANK": "ICICIBANK",
    "TCS": "TCS", "INFOSYS": "INFY", "SBI": "SBIN", "TATA MOTORS": "TATAMOTORS",
    "ITC": "ITC", "WIPRO": "WIPRO", "ADANI ENT": "ADANIENT",
    "ADANI PORTS": "ADANIPORTS", "BAJAJ FINANCE": "BAJFINANCE",
    "BAJAJ FINSERV": "BAJAJFINSV", "HCL TECH": "HCLTECH", "AXIS BANK": "AXISBANK",
    "KOTAK BANK": "KOTAKBANK", "L&T": "LT", "MARUTI": "MARUTI",
    "ASIAN PAINTS": "ASIANPAINT", "TITAN": "TITAN", "ULTRATECH": "ULTRACEMCO",
    "SUN PHARMA": "SUNPHARMA", "BHARTI AIRTEL": "BHARTIARTL",
    "POWER GRID": "POWERGRID", "NTPC": "NTPC", "ONGC": "ONGC",
    "COAL INDIA": "COALINDIA", "TATA STEEL": "TATASTEEL",
    "JSW STEEL": "JSWSTEEL", "HINDALCO": "HINDALCO", "GRASIM": "GRASIM",
    "TECH MAHINDRA": "TECHM", "M&M": "M&M", "HERO MOTOCORP": "HEROMOTOCO",
    "EICHER MOTORS": "EICHERMOT", "BPCL": "BPCL", "IOC": "IOC",
    "CIPLA": "CIPLA", "DR REDDY": "DRREDDY", "DIVIS LAB": "DIVISLAB",
    "APOLLO HOSPITAL": "APOLLOHOSP", "TATA CONSUMER": "TATACONSUM",
    "BRITANNIA": "BRITANNIA", "NESTLE": "NESTLEIND", "HINDUSTAN UNILEVER": "HINDUNILVR",
    "DABUR": "DABUR", "GODREJ CP": "GODREJCP", "PIDILITE": "PIDILITIND",
    "BERGER PAINTS": "BERGEPAINT", "HAVELLS": "HAVELLS",
    "ABB INDIA": "ABB", "SIEMENS": "SIEMENS", "BHEL": "BHEL",
    "INDUSINDBK": "INDUSINDBK", "BANDHAN BANK": "BANDHANBNK",
    "PNB": "PNB", "CANARA BANK": "CANBK", "FEDERAL BANK": "FEDERALBNK",
    "IDEA (VI)": "IDEA", "ZOMATO": "ZOMATO", "PAYTM": "PAYTM",
    "NYKAA": "NYKAA", "DELHIVERY": "DELHIVERY",
    "TRENT": "TRENT", "VEDANTA": "VEDL", "JINDAL STEEL": "JINDALSTEL",
    "DLF": "DLF", "GODREJ PROP": "GODREJPROP", "SAIL": "SAIL",
    "HAL": "HAL", "BEL": "BEL", "IRCTC": "IRCTC",
    "INDIAN HOTELS": "INDHOTEL", "LIC HOUSING": "LICHSGFIN",
    "MANAPPURAM": "MANAPPURAM", "MUTHOOT FIN": "MUTHOOTFIN",
    "PEL": "PEL", "VOLTAS": "VOLTAS", "CROMPTON": "CROMPTON",
    "MRF": "MRF", "BALKRISHNA IND": "BALKRISIND",
    "POLYCAB": "POLYCAB", "COFORGE": "COFORGE", "MPHASIS": "MPHASIS",
    "L&T TECH": "LTTS", "PERSISTENT": "PERSISTENT",
    "TATA POWER": "TATAPOWER", "ADANI GREEN": "ADANIGREEN",
    "NHPC": "NHPC", "PFC": "PFC", "REC": "RECLTD",
    "SBILIFE": "SBILIFE", "HDFC LIFE": "HDFCLIFE", "ICICI PRU LIFE": "ICICIPRULI",
    "BAJAJ AUTO": "BAJAJ-AUTO", "TVS MOTOR": "TVSMOTOR",
    "ASHOK LEYLAND": "ASHOKLEY", "BHARAT FORGE": "BHARATFORG",
    "SHRIRAM FIN": "SHRIRAMFIN", "CHOLAFIN": "CHOLAFIN",
    "INDIGO (INTERGLOBE)": "INDIGO", "DEEPAK NITRITE": "DEEPAKNTR",
    "ASTRAL": "ASTRAL", "AU SMALL FIN": "AUBANK",
    "CANFIN HOMES": "CANFINHOME", "CHAMBAL FERT": "CHAMBLFERT",
    "COLGATE": "COLPAL", "CUB": "CUB", "CUMMINS INDIA": "CUMMINSIND",
    "ESCORTS": "ESCORTS", "EXIDE IND": "EXIDEIND",
    "GLENMARK": "GLENMARK", "GMR AIRPORTS": "GMRINFRA",
    "GRANULES": "GRANULES", "GUJGAS": "GUJGASLTD",
    "IPCALAB": "IPCALAB", "JUBILANT FOOD": "JUBLFOOD",
    "LAURUS LABS": "LAURUSLABS", "LUPIN": "LUPIN",
    "MAX HEALTH": "MAXHEALTH", "MCX": "MCX",
    "METROPOLIS": "METROPOLIS", "MFSL": "MFSL",
    "NAM INDIA": "NAM-INDIA", "NAUKRI (INFO EDGE)": "NAUKRI",
    "OBEROI REALTY": "OBEROIRLTY", "PAGE IND": "PAGEIND",
    "PETRONET": "PETRONET", "PHOENIX MILLS": "PHOENIXLTD",
    "PI IND": "PIIND", "RAMCO CEMENTS": "RAMCOCEM",
    "SRF": "SRF", "TORRENT PHARMA": "TORNTPHARM",
    "UPL": "UPL", "BIOCON": "BIOCON",
}

# Lot sizes for popular instruments
LOT_SIZES = {
    "NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 40, "MIDCPNIFTY": 50,
    "SENSEX": 20, "BANKEX": 30,
    "RELIANCE": 250, "HDFCBANK": 550, "ICICIBANK": 700, "TCS": 150,
    "INFY": 300, "SBIN": 750, "TATAMOTORS": 575, "ITC": 1600,
    "WIPRO": 1500, "ADANIENT": 250, "BAJFINANCE": 125, "AXISBANK": 600,
    "KOTAKBANK": 400, "LT": 150, "MARUTI": 100, "TITAN": 225,
    "SUNPHARMA": 350, "BHARTIARTL": 475, "TATASTEEL": 500,
    "HINDUNILVR": 300, "TECHM": 600, "M&M": 350,
}

st.set_page_config(page_title="NSE Trading Signals", page_icon="📊", layout="wide")

# ── Custom CSS ──
st.markdown("""
<style>
    .block-container { padding-top: 1rem; max-width: 100%; }

    .trade-card { padding: 16px; border-radius: 12px; margin: 8px 0; }
    .trade-open { background: linear-gradient(135deg, #064e3b, #065f46); border: 1px solid #10b981; }
    .trade-closed-profit { background: linear-gradient(135deg, #064e3b, #065f46); border: 1px solid #22c55e; }
    .trade-closed-loss { background: linear-gradient(135deg, #7f1d1d, #991b1b); border: 1px solid #ef4444; }
    .trade-card h3 { margin: 0 0 6px 0; color: white; font-size: 1.15em; }
    .trade-card .detail { color: #d1d5db; font-size: 0.92em; margin: 3px 0; }
    .trade-card .detail b { color: #fbbf24; }
    .trade-card .pnl { font-size: 1.1em; font-weight: 700; margin-top: 6px; }

    .action-panel { padding: 20px; border-radius: 14px; margin: 10px 0; }
    .action-buy { background: linear-gradient(135deg, #064e3b, #065f46); border: 2px solid #10b981; }
    .action-sell { background: linear-gradient(135deg, #7f1d1d, #991b1b); border: 2px solid #ef4444; }
    .action-hold { background: linear-gradient(135deg, #78350f, #92400e); border: 2px solid #f59e0b; }
    .action-panel h2 { margin: 0 0 8px 0; color: white; font-size: 1.6em; }
    .action-panel .step { color: #e5e7eb; font-size: 1em; margin: 6px 0; padding: 8px 12px; background: rgba(0,0,0,0.2); border-radius: 8px; }
    .action-panel .step b { color: #fbbf24; }

    .option-card { background: #1a1a2e; padding: 16px; border-radius: 12px; border: 1px solid #6366f1; margin: 8px 0; }
    .option-card h3 { margin: 0 0 10px 0; color: #a5b4fc; font-size: 1.1em; }
    .option-card .contract { font-size: 1.4em; font-weight: 800; color: #22d3ee; margin: 6px 0; }
    .option-card .detail { color: #cbd5e1; font-size: 0.9em; margin: 3px 0; }

    .chat-container { max-height: 500px; overflow-y: auto; padding: 10px; }
    .chat-msg { max-width: 85%; padding: 12px 16px; border-radius: 12px; margin: 8px 0; font-size: 0.9em; line-height: 1.6; }
    .chat-buy { background: #065f46; color: #d1fae5; border-bottom-left-radius: 4px; }
    .chat-sell { background: #991b1b; color: #fee2e2; border-bottom-left-radius: 4px; }
    .chat-hold { background: #92400e; color: #fef3c7; border-bottom-left-radius: 4px; }
    .chat-time { font-size: 0.7em; color: rgba(255,255,255,0.5); text-align: right; margin-top: 4px; }

    .indicator-card { background: #1e1e2e; padding: 14px; border-radius: 10px; border: 1px solid #30363d; margin: 4px 0; text-align: center; }
    .indicator-card h4 { margin: 0 0 6px 0; color: #94a3b8; font-size: 0.75em; text-transform: uppercase; letter-spacing: 1px; }
    .indicator-card .value { font-size: 1.5em; font-weight: bold; color: white; }
    .badge { display: inline-block; padding: 2px 10px; border-radius: 4px; font-size: 0.7em; font-weight: 700; color: white; margin-top: 6px; }
    .badge-buy { background: #059669; }
    .badge-sell { background: #dc2626; }
    .badge-neutral { background: #6b7280; }
    .news-item { background: #1e1e2e; padding: 10px 14px; border-radius: 8px; margin: 6px 0; border-left: 4px solid #6b7280; }
    .news-item.bullish { border-left-color: #22c55e; }
    .news-item.bearish { border-left-color: #ef4444; }
    .analysis-box { background: linear-gradient(135deg, #1e1e2e, #252547); padding: 16px; border-radius: 10px; border: 1px solid #6366f1; }
    div[data-testid="stSidebar"] { background: #0f0f1a; }
    .signal-table { width: 100%; border-collapse: collapse; font-size: 0.85em; }
    .signal-table th { background: #1e293b; color: #94a3b8; padding: 8px 12px; text-align: left; }
    .signal-table td { padding: 8px 12px; border-bottom: 1px solid #1e293b; color: #e5e7eb; }

    .sms-log-table { width: 100%; border-collapse: collapse; font-size: 0.82em; margin-top: 8px; }
    .sms-log-table th { background: #1e293b; color: #94a3b8; padding: 6px 10px; text-align: left; }
    .sms-log-table td { padding: 6px 10px; border-bottom: 1px solid #1e293b; color: #e5e7eb; }

    .sub-table { width: 100%; border-collapse: collapse; font-size: 0.85em; }
    .sub-table th { background: #1e293b; color: #94a3b8; padding: 6px 10px; text-align: left; }
    .sub-table td { padding: 6px 10px; border-bottom: 1px solid #1e293b; color: #e5e7eb; }

    .alert-banner { animation: pulse 2s infinite; }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.7; } }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════
#  SIDEBAR — Settings & Controls
# ══════════════════════════════════════════

with st.sidebar:
    st.markdown("## ⚙️ Settings")

    selected_symbol = st.selectbox("Select Stock / Index", list(SYMBOLS.keys()), index=0)
    sym = SYMBOLS[selected_symbol]

    chart_period = st.selectbox("Chart Period", ["1d", "5d", "1mo"], index=1)
    chart_interval = st.selectbox("Interval", ["1m", "5m", "15m", "30m", "1h"], index=1)

    if st.button("🔄 Refresh Data", use_container_width=True, type="primary"):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    now = datetime.now(IST)
    if is_market_open():
        st.success("🟢 Market Open")
    else:
        st.warning("🔴 Market Closed")
    st.caption(now.strftime("%d %b %Y, %I:%M %p IST"))

    st.divider()
    st.markdown("##### 📧 Email Alerts")
    email_on = st.toggle("Send email on BUY/SELL", value=bool(EMAIL_SENDER and EMAIL_RECEIVER))
    sender = st.text_input("Sender Gmail", value=EMAIL_SENDER, type="default")
    app_pwd = st.text_input("App Password", value=EMAIL_PASSWORD, type="password")
    receiver = st.text_input("Client Email", value=EMAIL_RECEIVER)

    st.divider()
    st.markdown("##### How it works")
    st.caption("📊 Lightweight chart with indicators")
    st.caption("🔄 Click 'Refresh Data' to update")
    st.caption("🔔 Sound + email alert on BUY/SELL")
    st.caption("📱 SMS broadcast to subscribers")
    st.caption(f"🛑 SL: {STOP_LOSS_PCT}% | Target: {TARGET_PCT}%")


# ══════════════════════════════════════════
#  DATA FETCHING
# ══════════════════════════════════════════

@st.cache_data(ttl=120)
def fetch_data(yf_symbol, nse_symbol, period, interval):
    spot, df, oi = None, pd.DataFrame(), None
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            price_future = executor.submit(get_spot_price, yf_symbol)
            df_future = executor.submit(get_intraday_data, yf_symbol, period, interval)
            oi_future = executor.submit(get_option_chain_data, nse_symbol) if nse_symbol else None

            try:
                spot = price_future.result(timeout=45)
            except Exception:
                spot = None
            try:
                df = df_future.result(timeout=45)
            except Exception:
                df = pd.DataFrame()
            try:
                oi = oi_future.result(timeout=20) if oi_future else None
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
    if sig["action"] in ("BUY", "SELL") and nse_sym in ("NIFTY", "BANKNIFTY", "FINNIFTY"):
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
    inst_data = compute_for_symbol(sym["yf"], sym["nse"], chart_period, chart_interval)
    news = fetch_news()

if not inst_data:
    st.error(f"Could not fetch data for {selected_symbol}.")
    st.stop()

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


# ══════════════════════════════════════════
#  BROWSER SOUND ALERT + EMAIL
# ══════════════════════════════════════════

action = signal["action"]
alert_key = f"last_signal_{selected_symbol}"
last_a = st.session_state.get(alert_key, None)
if action in ("BUY", "SELL") and action != last_a:
    st.session_state[alert_key] = action
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

    if email_on and sender and app_pwd and receiver:
        email_ok = send_signal_email(
            sender, app_pwd, receiver,
            selected_symbol, signal, option_rec,
        )
        if email_ok:
            st.toast(f"📧 Email sent to {receiver}!", icon="✅")
        else:
            st.toast("📧 Email failed — check credentials", icon="❌")

elif action == "HOLD":
    st.session_state[alert_key] = "HOLD"


# ══════════════════════════════════════════
#  HEADER
# ══════════════════════════════════════════

day_change = df["Close"].iloc[-1] - df["Open"].iloc[0]
day_pct = (day_change / df["Open"].iloc[0]) * 100
color = "#22c55e" if day_change >= 0 else "#ef4444"
arrow = "▲" if day_change >= 0 else "▼"

st.markdown(f"## {selected_symbol} — ₹{spot_price:,.2f}")
st.markdown(f'<span style="color:{color};font-size:1.1em;font-weight:600;">{arrow} ₹{abs(day_change):,.2f} ({day_pct:+.2f}%)</span> &nbsp; <span style="color:#6b7280;">H: ₹{df["High"].max():,.2f} &nbsp; L: ₹{df["Low"].min():,.2f}</span>', unsafe_allow_html=True)


# ══════════════════════════════════════════
#  TABS: Trading | Chart & Signals | News & AI | SMS Admin
# ══════════════════════════════════════════

tab_trade, tab_chart, tab_news, tab_sms = st.tabs([
    "📝 Create Trade", "📊 Chart & Signals", "📰 News & AI", "📱 SMS Admin"
])


# ── TAB 1: CREATE TRADE + OPEN/CLOSED TRADES ──
with tab_trade:
    trade_col, trades_col = st.columns([2, 3])

    with trade_col:
        st.markdown("### 📝 New Trade")

        # Searchable instrument dropdown
        instrument_names = sorted(FNO_INSTRUMENTS.keys())
        selected_instrument = st.selectbox(
            "Instrument (type to search)",
            instrument_names,
            index=instrument_names.index("NIFTY 50") if "NIFTY 50" in instrument_names else 0,
            key="trade_instrument",
        )
        nse_symbol = FNO_INSTRUMENTS[selected_instrument]

        col_strike, col_type = st.columns([2, 1])
        with col_strike:
            strike_price = st.number_input("Strike Price", min_value=0.0, value=0.0, step=50.0, format="%.0f")
        with col_type:
            option_type = st.selectbox("Type", ["CE", "PE"])

        expiry_date = st.text_input("Expiry Date", placeholder="e.g. 29-May, 05-Jun", value="")

        col_entry, col_target, col_sl = st.columns(3)
        with col_entry:
            entry_price = st.number_input("Entry Price (₹)", min_value=0.0, value=0.0, step=1.0, format="%.2f")
        with col_target:
            target_price = st.number_input("Target Price (₹)", min_value=0.0, value=0.0, step=1.0, format="%.2f")
        with col_sl:
            stop_loss_price = st.number_input("Stop Loss (₹)", min_value=0.0, value=0.0, step=1.0, format="%.2f")

        col_qty, col_lot = st.columns(2)
        with col_qty:
            default_lot = LOT_SIZES.get(nse_symbol, 1)
            quantity = st.number_input("Quantity (lots)", min_value=1, value=1, step=1)
        with col_lot:
            lot_size = st.number_input("Lot Size", min_value=1, value=default_lot, step=1)

        # Preview
        if strike_price > 0 and entry_price > 0 and expiry_date:
            preview = (
                f"**BUY {selected_instrument} {int(strike_price)} {option_type} "
                f"({expiry_date}) @ ₹{entry_price:,.2f}**"
            )
            if target_price > 0:
                preview += f" → Target ₹{target_price:,.2f}"
            if stop_loss_price > 0:
                preview += f" | SL ₹{stop_loss_price:,.2f}"
            preview += f" | Qty {quantity} lot{'s' if quantity > 1 else ''}"
            st.info(preview)

        if st.button("🚀 Create Trade & Send SMS", use_container_width=True, type="primary"):
            if strike_price <= 0 or entry_price <= 0 or not expiry_date.strip():
                st.error("Please fill in Strike Price, Entry Price, and Expiry Date.")
            else:
                trade = create_trade(
                    instrument=selected_instrument,
                    strike=strike_price,
                    option_type=option_type,
                    expiry=expiry_date.strip(),
                    entry_price=entry_price,
                    target_price=target_price,
                    stop_loss=stop_loss_price,
                    quantity=quantity,
                    lot_size=lot_size,
                )
                st.success(f"✅ Trade created: {format_trade_display(trade)}")

                # Send SMS to all subscribers
                sms_results = send_sms_to_all(trade, action="BUY")
                if sms_results:
                    sent_count = sum(1 for r in sms_results if r["status"] != "failed")
                    fail_count = sum(1 for r in sms_results if r["status"] == "failed")
                    if sent_count > 0:
                        st.success(f"📱 SMS sent to {sent_count} subscriber(s)")
                    if fail_count > 0:
                        st.warning(f"⚠️ {fail_count} SMS failed to send")
                else:
                    st.info("No subscribers to send SMS to.")

                # Also send email if configured
                if email_on and sender and app_pwd and receiver:
                    trade_signal = {
                        "action": "BUY",
                        "entry_price": entry_price,
                        "stop_loss": stop_loss_price if stop_loss_price > 0 else entry_price * 0.97,
                        "target": target_price if target_price > 0 else entry_price * 1.03,
                    }
                    send_signal_email(sender, app_pwd, receiver, selected_instrument, trade_signal, None)

                st.rerun()

    with trades_col:
        # ── Open Trades ──
        st.markdown("### 🟢 Open Trades")
        open_trades = get_open_trades()
        if open_trades:
            for t in reversed(open_trades):
                card_html = f'<div class="trade-card trade-open">'
                card_html += f'<h3>🟢 BUY {t["instrument"]} {int(t["strike"])} {t["option_type"]} ({t["expiry"]})</h3>'
                card_html += f'<div class="detail">Entry: <b>₹{t["entry_price"]:,.2f}</b>'
                if t["target_price"] > 0:
                    card_html += f' | Target: <b>₹{t["target_price"]:,.2f}</b>'
                if t["stop_loss"] > 0:
                    card_html += f' | SL: <b>₹{t["stop_loss"]:,.2f}</b>'
                card_html += f'</div>'
                card_html += f'<div class="detail">Qty: {t["quantity"]} lot(s) x {t["lot_size"]} = {t["quantity"] * t["lot_size"]} units</div>'
                card_html += f'<div class="detail" style="color:#6b7280;font-size:0.8em;">ID: {t["id"]} | {t["created_at"][:16]}</div>'
                card_html += '</div>'
                st.markdown(card_html, unsafe_allow_html=True)

                # Close trade controls
                ecol1, ecol2, ecol3 = st.columns([2, 1, 1])
                with ecol1:
                    exit_p = st.number_input(
                        f"Exit Price", min_value=0.0, value=0.0, step=1.0,
                        format="%.2f", key=f"exit_{t['id']}"
                    )
                with ecol2:
                    if st.button("Close Trade", key=f"close_{t['id']}"):
                        if exit_p > 0:
                            closed = close_trade(t["id"], exit_p)
                            if closed:
                                # Send EXIT SMS
                                sms_results = send_sms_to_all(closed, action="EXIT")
                                sent_count = sum(1 for r in sms_results if r["status"] != "failed") if sms_results else 0
                                sign = "+" if closed["pnl"] >= 0 else ""
                                st.success(f"Trade closed. P&L: {sign}₹{closed['pnl']:,.2f} | SMS sent to {sent_count}")
                                st.rerun()
                        else:
                            st.error("Enter exit price")
                with ecol3:
                    if st.button("🗑️", key=f"del_{t['id']}"):
                        delete_trade(t["id"])
                        st.rerun()
        else:
            st.info("No open trades. Create one using the form on the left.")

        # ── Closed Trades ──
        st.markdown("### 📕 Closed Trades")
        closed_trades = get_closed_trades()
        if closed_trades:
            total_pnl = sum(t.get("pnl", 0) for t in closed_trades)
            sign = "+" if total_pnl >= 0 else ""
            pnl_color = "#22c55e" if total_pnl >= 0 else "#ef4444"
            st.markdown(f'<p style="font-size:1.1em;">Total P&L: <span style="color:{pnl_color};font-weight:700;">{sign}₹{total_pnl:,.2f}</span> ({len(closed_trades)} trades)</p>', unsafe_allow_html=True)

            for t in reversed(closed_trades[-10:]):
                pnl = t.get("pnl", 0)
                css_class = "trade-closed-profit" if pnl >= 0 else "trade-closed-loss"
                sign = "+" if pnl >= 0 else ""
                pnl_color = "#22c55e" if pnl >= 0 else "#ef4444"
                card_html = f'<div class="trade-card {css_class}">'
                card_html += f'<h3>{"✅" if pnl >= 0 else "❌"} {t["instrument"]} {int(t["strike"])} {t["option_type"]} ({t["expiry"]})</h3>'
                card_html += f'<div class="detail">Entry: <b>₹{t["entry_price"]:,.2f}</b> → Exit: <b>₹{t["exit_price"]:,.2f}</b></div>'
                card_html += f'<div class="pnl" style="color:{pnl_color};">P&L: {sign}₹{pnl:,.2f}</div>'
                card_html += f'<div class="detail" style="color:#6b7280;font-size:0.8em;">{t.get("exit_time", "")[:16]}</div>'
                card_html += '</div>'
                st.markdown(card_html, unsafe_allow_html=True)
        else:
            st.info("No closed trades yet.")


# ── TAB 2: CHART & SIGNALS ──
with tab_chart:
    # ── Action Panel + Chat ──
    action_col, chat_col = st.columns([3, 2])

    with action_col:
        if action == "BUY":
            panel_css = "action-buy"
            icon_str = "🟢 BUY"
            if option_rec:
                steps_html = '<div class="step">📌 Step 1: Open broker (Zerodha / Groww / Angel One)</div>'
                steps_html += f'<div class="step">📌 Step 2: Search <b>{option_rec["contract"]}</b></div>'
                steps_html += f'<div class="step">📌 Step 3: Buy <b>{option_rec["lot_size"]} qty</b> at ≈ <b>₹{option_rec["ltp"]:,.2f}</b></div>'
                steps_html += f'<div class="step">💵 Total cost: <b>₹{option_rec["total_premium"]:,.2f}</b></div>'
                steps_html += f'<div class="step">🛑 Exit if premium drops to <b>₹{option_rec["premium_sl"]:,.2f}</b></div>'
                steps_html += f'<div class="step">🎯 Book profit at <b>₹{option_rec["premium_target"]:,.2f}</b></div>'
            else:
                steps_html = f'<div class="step">📌 Open broker → Search <b>{selected_symbol}</b> → Buy CE (Call)</div>'
                steps_html += f'<div class="step">📌 Pick ATM strike nearest to <b>₹{spot_price:,.0f}</b></div>'
                steps_html += f'<div class="step">🛑 Stop Loss: <b>₹{signal["stop_loss"]:,.2f}</b></div>'
                steps_html += f'<div class="step">🎯 Target: <b>₹{signal["target"]:,.2f}</b></div>'
        elif action == "SELL":
            panel_css = "action-sell"
            icon_str = "🔴 SELL"
            if option_rec:
                steps_html = '<div class="step">📌 Step 1: Open broker (Zerodha / Groww / Angel One)</div>'
                steps_html += f'<div class="step">📌 Step 2: Search <b>{option_rec["contract"]}</b></div>'
                steps_html += f'<div class="step">📌 Step 3: Buy <b>{option_rec["lot_size"]} qty</b> at ≈ <b>₹{option_rec["ltp"]:,.2f}</b></div>'
                steps_html += f'<div class="step">💵 Total cost: <b>₹{option_rec["total_premium"]:,.2f}</b></div>'
                steps_html += f'<div class="step">🛑 Exit if premium drops to <b>₹{option_rec["premium_sl"]:,.2f}</b></div>'
                steps_html += f'<div class="step">🎯 Book profit at <b>₹{option_rec["premium_target"]:,.2f}</b></div>'
            else:
                steps_html = f'<div class="step">📌 Open broker → Search <b>{selected_symbol}</b> → Buy PE (Put)</div>'
                steps_html += f'<div class="step">📌 Pick ATM strike nearest to <b>₹{spot_price:,.0f}</b></div>'
                steps_html += f'<div class="step">🛑 Stop Loss: <b>₹{signal["stop_loss"]:,.2f}</b></div>'
                steps_html += f'<div class="step">🎯 Target: <b>₹{signal["target"]:,.2f}</b></div>'
        else:
            panel_css = "action-hold"
            icon_str = "🟡 HOLD"
            steps_html = '<div class="step">⏸️ No clear signal. <b>Don\'t trade right now.</b></div>'
            steps_html += f'<div class="step">💡 {signal["buy_count"]} BUY / {signal["sell_count"]} SELL — need 3+ to align</div>'
            steps_html += '<div class="step">📖 Keep tab open. Sound alert when signal fires.</div>'

        alert_class = ' alert-banner' if action in ("BUY", "SELL") else ''
        panel_html = f'<div class="action-panel {panel_css}{alert_class}"><h2>{icon_str} {selected_symbol} — What to do now</h2>{steps_html}</div>'
        st.markdown(panel_html, unsafe_allow_html=True)

        if option_rec:
            opt_html = f'<div class="option-card"><h3>📋 Option Contract</h3>'
            opt_html += f'<div class="contract">{option_rec["contract"]}</div>'
            opt_html += f'<div class="detail">Expiry: <b>{option_rec["expiry"]}</b></div>'
            opt_html += f'<div class="detail">Premium: <b>₹{option_rec["ltp"]:,.2f}</b> | Bid: ₹{option_rec["bid"]:,.2f} Ask: ₹{option_rec["ask"]:,.2f}</div>'
            opt_html += f'<div class="detail">Lot: <b>{option_rec["lot_size"]}</b> | Total: <b>₹{option_rec["total_premium"]:,.2f}</b></div>'
            opt_html += f'<div class="detail">OI: {option_rec["oi"]:,} | OI Δ: {option_rec["oi_change"]:,} | IV: {option_rec["iv"]}%</div>'
            opt_html += f'<div class="detail" style="margin-top:8px;font-weight:700;">🛑 SL: ₹{option_rec["premium_sl"]:,.2f} | 🎯 Target: ₹{option_rec["premium_target"]:,.2f}</div>'
            opt_html += '</div>'
            st.markdown(opt_html, unsafe_allow_html=True)

    with chat_col:
        st.markdown(f"### 💬 {selected_symbol} Signals")
        chat_html = '<div class="chat-container">'
        now_str = datetime.now(IST).strftime("%I:%M %p")
        chat_css = f"chat-{action.lower()}"
        chat_text = format_signal_chat(signal, selected_symbol, "")
        chat_html += f'<div class="chat-msg {chat_css}">{chat_text}<div class="chat-time">{now_str} ✓✓</div></div>'

        for s in reversed(all_signals[-5:]):
            ts = s["index"].strftime("%I:%M %p, %d %b") if hasattr(s["index"], "strftime") else str(s["index"])
            s_css = "chat-buy" if s["action"] == "BUY" else "chat-sell"
            opt_type = "CE" if s["action"] == "BUY" else "PE"
            s_icon = "🟢" if s["action"] == "BUY" else "🔴"
            chat_html += f'<div class="chat-msg {s_css}">{s_icon} <b>{s["action"]} {selected_symbol}</b><br>📍 ₹{s["price"]:,.2f} → Buy {opt_type}<br>🛑 SL: ₹{s["sl"]:,.2f} &nbsp; 🎯 T: ₹{s["target"]:,.2f}<div class="chat-time">{ts}</div></div>'
        chat_html += '</div>'
        st.markdown(chat_html, unsafe_allow_html=True)

    st.markdown("---")

    # ── Chart ──
    def build_chart_html(chart_id, chart_df, v_data, st_data, r_data, m_data, sig_list):
        IST_OFFSET = 19800

        candles, volumes = [], []
        for idx, row in chart_df.iterrows():
            ts = int(idx.timestamp()) + IST_OFFSET
            candles.append({"time": ts, "open": round(float(row["Open"]), 2), "high": round(float(row["High"]), 2), "low": round(float(row["Low"]), 2), "close": round(float(row["Close"]), 2)})
            vc = "rgba(38,166,154,0.5)" if row["Close"] >= row["Open"] else "rgba(239,83,80,0.5)"
            volumes.append({"time": ts, "value": float(row["Volume"]), "color": vc})

        vwap_pts = [{"time": int(i.timestamp()) + IST_OFFSET, "value": round(float(v), 2)} for i, v in v_data["series"].items() if pd.notna(v)]
        st_pts = [{"time": int(i.timestamp()) + IST_OFFSET, "value": round(float(v), 2)} for i, v in st_data["series"].items() if v != 0 and pd.notna(v)]
        rsi_pts = [{"time": int(i.timestamp()) + IST_OFFSET, "value": round(float(v), 2)} for i, v in r_data["series"].items() if pd.notna(v)]
        ml_pts = [{"time": int(i.timestamp()) + IST_OFFSET, "value": round(float(v), 2)} for i, v in m_data["macd_series"].items() if pd.notna(v)]
        ms_pts = [{"time": int(i.timestamp()) + IST_OFFSET, "value": round(float(v), 2)} for i, v in m_data["signal_series"].items() if pd.notna(v)]
        mh_pts = [{"time": int(i.timestamp()) + IST_OFFSET, "value": round(float(v), 2), "color": "rgba(38,166,154,0.7)" if v >= 0 else "rgba(239,83,80,0.7)"} for i, v in m_data["hist_series"].items() if pd.notna(v)]

        markers = []
        for s in sig_list:
            ts = int(s["index"].timestamp()) + IST_OFFSET
            opt = "CE" if s["action"] == "BUY" else "PE"
            if s["action"] == "BUY":
                markers.append({"time": ts, "position": "belowBar", "color": "#26a69a", "shape": "arrowUp", "text": f"BUY {opt} @{s['price']:,.0f}"})
            else:
                markers.append({"time": ts, "position": "aboveBar", "color": "#ef5350", "shape": "arrowDown", "text": f"SELL {opt} @{s['price']:,.0f}"})
        markers.sort(key=lambda m: m["time"])

        cid = f"c{chart_id}"
        mc, vc_id, rc, dc = f"mc{cid}", f"vc{cid}", f"rc{cid}", f"dc{cid}"

        return f"""<!DOCTYPE html><html><head>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>
body{{margin:0;background:#0e1117;font-family:-apple-system,sans-serif}}
#{mc}{{width:100%;height:400px}}#{vc_id}{{width:100%;height:60px}}#{rc}{{width:100%;height:90px}}#{dc}{{width:100%;height:90px}}
.lb{{color:#94a3b8;font-size:11px;font-weight:600;padding:3px 12px;background:#0e1117;border-bottom:1px solid #1e293b;letter-spacing:1px}}
.lg{{display:flex;gap:14px;padding:6px 12px;background:#0e1117;border-bottom:1px solid #1e293b;flex-wrap:wrap}}
.lg span{{font-size:11px;color:#94a3b8;display:flex;align-items:center;gap:4px}}
.lg .d{{width:12px;height:3px;border-radius:2px;display:inline-block}}
</style></head><body>
<div class="lg">
<span><span class="d" style="background:#a78bfa"></span>VWAP</span>
<span><span class="d" style="background:#26a69a"></span>SuperTrend</span>
<span>🟢 BUY CE</span><span>🔴 SELL PE</span>
</div>
<div id="{mc}"></div><div class="lb">VOLUME</div><div id="{vc_id}"></div>
<div class="lb">RSI (14)</div><div id="{rc}"></div>
<div class="lb">MACD (12,26,9)</div><div id="{dc}"></div>
<script>
var CD={json.dumps(candles)},VD={json.dumps(volumes)},VP={json.dumps(vwap_pts)},SP={json.dumps(st_pts)},MK={json.dumps(markers)};
var RP={json.dumps(rsi_pts)},ML={json.dumps(ml_pts)},MS={json.dumps(ms_pts)},MH={json.dumps(mh_pts)};
function mk(el,h){{return LightweightCharts.createChart(el,{{width:el.clientWidth,height:h,layout:{{background:{{color:'#0e1117'}},textColor:'#94a3b8',fontSize:11}},grid:{{vertLines:{{color:'#1e293b'}},horzLines:{{color:'#1e293b'}}}},crosshair:{{mode:LightweightCharts.CrosshairMode.Normal}},rightPriceScale:{{borderColor:'#1e293b'}},timeScale:{{borderColor:'#1e293b',timeVisible:true,secondsVisible:false}}}})}}
var mc=mk(document.getElementById('{mc}'),400);
var cs=mc.addCandlestickSeries({{upColor:'#26a69a',downColor:'#ef5350',borderUpColor:'#26a69a',borderDownColor:'#ef5350',wickUpColor:'#26a69a',wickDownColor:'#ef5350'}});
cs.setData(CD);cs.setMarkers(MK);
mc.addLineSeries({{color:'#a78bfa',lineWidth:2,lineStyle:2,priceLineVisible:false,lastValueVisible:false}}).setData(VP);
mc.addLineSeries({{color:'#26a69a',lineWidth:2,priceLineVisible:false,lastValueVisible:false}}).setData(SP);
var vc=mk(document.getElementById('{vc_id}'),60);
vc.addHistogramSeries({{priceFormat:{{type:'volume'}},priceLineVisible:false,lastValueVisible:false}}).setData(VD);
var rc=mk(document.getElementById('{rc}'),90);
rc.addLineSeries({{color:'#f59e0b',lineWidth:2,priceLineVisible:false,lastValueVisible:true}}).setData(RP);
if(RP.length>1){{rc.addLineSeries({{color:'rgba(239,83,80,0.4)',lineWidth:1,lineStyle:2,priceLineVisible:false,lastValueVisible:false}}).setData([{{time:RP[0].time,value:70}},{{time:RP[RP.length-1].time,value:70}}]);rc.addLineSeries({{color:'rgba(38,166,154,0.4)',lineWidth:1,lineStyle:2,priceLineVisible:false,lastValueVisible:false}}).setData([{{time:RP[0].time,value:30}},{{time:RP[RP.length-1].time,value:30}}]);}}
var dc=mk(document.getElementById('{dc}'),90);
dc.addLineSeries({{color:'#3b82f6',lineWidth:1.5,priceLineVisible:false,lastValueVisible:false}}).setData(ML);
dc.addLineSeries({{color:'#f97316',lineWidth:1.5,priceLineVisible:false,lastValueVisible:false}}).setData(MS);
dc.addHistogramSeries({{priceLineVisible:false,lastValueVisible:false}}).setData(MH);
function sy(cs){{cs.forEach(function(c,i){{c.timeScale().subscribeVisibleLogicalRangeChange(function(r){{cs.forEach(function(o,j){{if(i!==j)o.timeScale().setVisibleLogicalRange(r)}})}})}})}}
sy([mc,vc,rc,dc]);
var tb=CD.length,vb=80;
if(tb>vb){{var rng={{from:tb-vb,to:tb+5}};[mc,vc,rc,dc].forEach(function(c){{c.timeScale().setVisibleLogicalRange(rng);}});}}
else{{[mc,vc,rc,dc].forEach(function(c){{c.timeScale().fitContent();}});}}
window.addEventListener('resize',function(){{var w=document.getElementById('{mc}').clientWidth;[mc,vc,rc,dc].forEach(function(c){{c.applyOptions({{width:w}})}});}});
</script></body></html>"""

    components.html(build_chart_html(0, df, vwap_data, supertrend, rsi, macd_data, all_signals), height=680, scrolling=False)

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
            opt_label = "Buy CE" if s["action"] == "BUY" else "Buy PE"
            rows += f'<tr><td>{ts}</td><td><span style="color:{ac};font-weight:700;">{"▲" if s["action"]=="BUY" else "▼"} {s["action"]}</span></td><td>{opt_label}</td><td>₹{s["price"]:,.2f}</td><td>₹{s["sl"]:,.2f}</td><td>₹{s["target"]:,.2f}</td></tr>'
        st.markdown(f'<table class="signal-table"><thead><tr><th>Time</th><th>Signal</th><th>Option</th><th>Entry</th><th>SL</th><th>Target</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)


# ── TAB 3: NEWS + AI ──
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
        prices_dict = {
            "nifty": inst_data["spot"] if sym["nse"] == "NIFTY" else None,
            "banknifty": inst_data["spot"] if sym["nse"] == "BANKNIFTY" else None,
        }
        with st.spinner("AI analyzing..."):
            analysis = analyze_market(
                prices_dict, signal, rsi, macd_data,
                supertrend, vwap_data, oi_data, news,
            )
        st.markdown(f'<div class="analysis-box"><p style="color:#e5e7eb;line-height:1.7;font-size:0.95em;">{analysis}</p></div>', unsafe_allow_html=True)


# ── TAB 4: SMS ADMIN ──
with tab_sms:
    sms_col1, sms_col2 = st.columns([1, 1])

    with sms_col1:
        st.markdown("### 📱 Subscriber Management")

        # Add subscriber
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

        # List subscribers
        st.markdown("##### Current Subscribers")
        subs = get_subscribers()
        if subs:
            sub_rows = ""
            for s in subs:
                status = "🟢 Active" if s.get("active", True) else "🔴 Inactive"
                sub_rows += f'<tr><td>{s.get("name", "-")}</td><td>{s["phone"]}</td><td>{status}</td><td>{s.get("added", "")[:10]}</td></tr>'
            st.markdown(f'<table class="sub-table"><thead><tr><th>Name</th><th>Phone</th><th>Status</th><th>Added</th></tr></thead><tbody>{sub_rows}</tbody></table>', unsafe_allow_html=True)

            # Remove subscriber
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
            st.info("No subscribers yet. Add phone numbers above.")

    with sms_col2:
        st.markdown("### 📋 SMS Delivery Log")
        sms_log = get_sms_log()
        if sms_log:
            log_rows = ""
            for entry in reversed(sms_log[-20:]):
                status_color = "#22c55e" if entry.get("status") != "failed" else "#ef4444"
                ts = entry.get("timestamp", "")[:16]
                phone = entry.get("phone", "")
                msg = entry.get("message", "")[:60]
                status = entry.get("status", "unknown")
                error = entry.get("error", "")
                log_rows += f'<tr><td>{ts}</td><td>{phone}</td><td style="color:{status_color};font-weight:600;">{status}</td><td title="{entry.get("message", "")}">{msg}...</td></tr>'
            st.markdown(f'<table class="sms-log-table"><thead><tr><th>Time</th><th>Phone</th><th>Status</th><th>Message</th></tr></thead><tbody>{log_rows}</tbody></table>', unsafe_allow_html=True)
        else:
            st.info("No SMS sent yet. Create a trade to broadcast.")

        # Manual SMS test
        st.markdown("##### 🧪 Send Test SMS")
        test_msg = st.text_input("Test message", value="Test: Trading signals active!", key="test_msg")
        if st.button("📤 Send Test to All", use_container_width=True):
            test_trade = {
                "instrument": "TEST",
                "strike": "0",
                "option_type": "CE",
                "expiry": "",
                "entry_price": 0,
                "target_price": 0,
                "stop_loss": 0,
                "quantity": 1,
            }
            results = send_sms_to_all(test_trade, action="BUY")
            if results:
                sent = sum(1 for r in results if r["status"] != "failed")
                st.success(f"Test SMS sent to {sent} subscriber(s)")
            else:
                st.info("No subscribers to send to.")


st.markdown("---")
st.caption("⚠️ For educational purposes only. Not financial advice. Always use stop loss.")
