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
    format_trade_display, delete_trade,
)
from sms_sender import (
    send_sms_to_all, get_subscribers, add_subscriber,
    remove_subscriber, get_sms_log,
)

IST = pytz.timezone("Asia/Kolkata")

st.set_page_config(page_title="NSE Trading Signals", page_icon="📊", layout="wide")

# Auto-refresh: 60s during market hours, 5 min when closed
_refresh_ms = 60_000 if is_market_open() else 300_000
st_autorefresh(interval=_refresh_ms, limit=0, key="live_refresh")

# ── Honest UX disclaimer ──
st.info("📢 Signals fire only while this browser tab is open. For 24/7 alerts, contact developer for upgrade.")

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

    .auto-sms-banner { background: linear-gradient(135deg, #1e1e2e, #252547); border: 1px solid #6366f1; border-radius: 10px; padding: 12px 16px; margin: 8px 0; }
    .auto-sms-banner .title { color: #a5b4fc; font-weight: 700; font-size: 0.95em; }
    .auto-sms-banner .info { color: #94a3b8; font-size: 0.82em; margin-top: 4px; }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════
#  SIDEBAR
# ══════════════════════════════════════════

def _make_sym(name: str) -> dict:
    """Auto-construct yf/nse/tv keys for any NSE symbol."""
    n = name.strip().upper()
    return {"yf": f"{n}.NS", "nse": n, "tv": f"NSE:{n}"}

with st.sidebar:
    st.markdown("## ⚙️ Settings")

    # Quick select from favorites OR type any NSE symbol
    all_symbols = list(SYMBOLS.keys())
    selected_symbol = st.selectbox("⭐ Quick Select", all_symbols, index=0, key="quick_sym")
    sym = SYMBOLS[selected_symbol]

    st.markdown('<p style="color:#6b7280;font-size:0.8em;margin:4px 0;">— OR type any NSE/BSE symbol —</p>', unsafe_allow_html=True)
    custom_sym = st.text_input("🔍 Any Symbol", placeholder="e.g. IDEA, BAJFINANCE, IRFC...", key="custom_sym")
    if custom_sym.strip():
        custom_upper = custom_sym.strip().upper()
        # Check if it's in our favorites first
        match = [k for k in SYMBOLS if custom_upper in k.upper() or custom_upper == SYMBOLS[k].get("nse", "").upper()]
        if match:
            selected_symbol = match[0]
            sym = SYMBOLS[selected_symbol]
        else:
            # Auto-construct for any NSE symbol
            selected_symbol = custom_upper
            sym = _make_sym(custom_upper)

    chart_period = st.selectbox("Chart Period", ["1d", "5d", "1mo"], index=1)
    chart_interval = st.selectbox("Interval", ["1m", "5m", "15m", "30m", "1h"], index=1)

    if st.button("🔄 Refresh Now", use_container_width=True, type="primary"):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    now = datetime.now(IST)
    if is_market_open():
        st.success("🟢 Market Open — Auto SMS Active")
    else:
        st.warning("🔴 Market Closed")
    st.caption(now.strftime("%d %b %Y, %I:%M %p IST"))

    # ── Watchlist (loads only during market hours, cached 2 min) ──
    st.divider()
    st.markdown("##### 👀 Watchlist")
    WATCHLIST_SYMBOLS = ["NIFTY 50", "BANK NIFTY", "SENSEX", "RELIANCE", "HDFC BANK", "TCS"]

    if is_market_open():
        @st.cache_data(ttl=120)
        def fetch_watchlist_prices():
            results = {}
            def _fetch(name):
                try:
                    return name, get_spot_price(SYMBOLS[name]["yf"])
                except Exception:
                    return name, None
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
                for f in concurrent.futures.as_completed([ex.submit(_fetch, n) for n in WATCHLIST_SYMBOLS]):
                    n, p = f.result()
                    results[n] = p
            return results
        wl_prices = fetch_watchlist_prices()
    else:
        wl_prices = {}

    wl_html = ""
    for wl_name in WATCHLIST_SYMBOLS:
        p = wl_prices.get(wl_name)
        if p is not None:
            wl_html += f'<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #1e293b;"><span style="color:#e5e7eb;font-size:0.85em;">{wl_name}</span><span style="color:#22c55e;font-size:0.85em;font-weight:600;">₹{p:,.2f}</span></div>'
        else:
            wl_html += f'<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #1e293b;"><span style="color:#e5e7eb;font-size:0.85em;">{wl_name}</span><span style="color:#6b7280;font-size:0.85em;">--</span></div>'
    st.markdown(f'<div style="background:#0f0f1a;border-radius:8px;padding:8px 10px;">{wl_html}</div>', unsafe_allow_html=True)

    st.divider()
    st.markdown("##### 📧 Email Alerts")
    email_on = st.toggle("Send email on BUY/SELL", value=bool(EMAIL_SENDER and EMAIL_RECEIVER))
    sender = st.text_input("Sender Gmail", value=EMAIL_SENDER, type="default")
    app_pwd = st.text_input("App Password", value=EMAIL_PASSWORD, type="password")
    receiver = st.text_input("Client Email", value=EMAIL_RECEIVER)

    st.divider()
    subs = get_subscribers()
    st.markdown(f"##### 📱 SMS: {len(subs)} subscriber(s)")
    st.caption("🤖 Auto-detects BUY/SELL signals")
    st.caption("📱 Sends SMS with option details")
    st.caption("⏱️ Scans every 60s during market hours")
    st.caption(f"🛑 SL: {STOP_LOSS_PCT}% | Target: {TARGET_PCT}%")


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

    # ── HEADER ──
    day_change = df["Close"].iloc[-1] - df["Open"].iloc[0]
    day_pct = (day_change / df["Open"].iloc[0]) * 100
    color = "#22c55e" if day_change >= 0 else "#ef4444"
    arrow = "▲" if day_change >= 0 else "▼"

    st.markdown(f"## {selected_symbol} — ₹{spot_price:,.2f}")
    st.markdown(f'<span style="color:{color};font-size:1.1em;font-weight:600;">{arrow} ₹{abs(day_change):,.2f} ({day_pct:+.2f}%)</span> &nbsp; <span style="color:#6b7280;">H: ₹{df["High"].max():,.2f} &nbsp; L: ₹{df["Low"].min():,.2f}</span>', unsafe_allow_html=True)

    if sms_sent_this_run:
        st.success(f"🚀 AUTO SIGNAL FIRED: {action} {selected_symbol} — SMS sent to {sms_sent_count} subscriber(s)" + (f", {sms_fail_count} failed" if sms_fail_count else ""))
    elif action in ("BUY", "SELL") and not cooldown_ok:
        remaining = 900 - int((datetime.now(IST) - last_signal_time).total_seconds())
        st.warning(f"⏳ Signal: {action} — cooldown active ({remaining // 60}m {remaining % 60}s left). Prevents whipsaw trades.")
    elif action in ("BUY", "SELL"):
        st.info(f"📱 Last signal: {action} — already sent (waiting for new signal)")
    else:
        st.markdown(f'<div class="auto-sms-banner"><div class="title">🤖 Auto-pilot active — scanning every 60s</div><div class="info">When BUY/SELL signal fires → auto picks option → auto sends SMS to {len(subs)} subscriber(s)</div></div>', unsafe_allow_html=True)

else:
    # Data fetch failed — show warning but DON'T stop the app
    st.warning(f"⚠️ Could not fetch market data for {selected_symbol}. Will retry on next auto-refresh (60s). Trades & SMS Admin still work below.")
    action = "HOLD"


# ══════════════════════════════════════════
#  TABS: Signals & Chart | Trades | News & AI | SMS Admin
# ══════════════════════════════════════════

tab_signals, tab_chart, tab_optchain, tab_trades, tab_portfolio, tab_news, tab_sms = st.tabs([
    "📊 Signals", "📈 Chart", "🔗 Option Chain", "📋 Trades", "💰 Portfolio", "📰 News & AI", "📱 SMS Admin"
])


# ── TAB 1: SIGNALS (no chart here anymore) ──
with tab_signals:
    if not data_ok:
        st.error(f"⚠️ Market data unavailable for {selected_symbol}. Auto-retrying every 60s. Check Trades & SMS Admin tabs — they still work.")
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


# ── TAB 2: CHART (TradingView Widget) ──
with tab_chart:
    tv_symbol = sym.get("tv", "NSE:NIFTY")
    # URL-encode the symbol (NSE:NIFTY -> NSE%3ANIFTY)
    import urllib.parse
    tv_encoded = urllib.parse.quote(tv_symbol, safe='')
    tv_widget_html = f"""
    <iframe
      src="https://s.tradingview.com/widgetembed/?frameElementId=tv_chart_embed&symbol={tv_encoded}&interval=5&symboledit=1&saveimage=1&toolbarbg=0e1117&theme=dark&style=1&timezone=Asia%2FKolkata&withdateranges=1&studies=RSI%40tv-basicstudies&studies=MACD%40tv-basicstudies&locale=en"
      style="width:100%;height:600px;border:none;"
      allowtransparency="true"
      frameborder="0"
      allowfullscreen>
    </iframe>
    """
    components.html(tv_widget_html, height=620, scrolling=False)

    if data_ok:
        sr = compute_support_resistance(df)
        # Show as colored cards in a row
        sr_html = '<div style="display:flex;gap:8px;margin-top:12px;justify-content:center;">'
        sr_html += f'<div style="background:#7f1d1d;padding:8px 16px;border-radius:8px;text-align:center;"><span style="color:#94a3b8;font-size:0.7em;">S2</span><br><span style="color:#ef4444;font-weight:700;">₹{sr["s2"]:,.2f}</span></div>'
        sr_html += f'<div style="background:#991b1b;padding:8px 16px;border-radius:8px;text-align:center;"><span style="color:#94a3b8;font-size:0.7em;">S1</span><br><span style="color:#f87171;font-weight:700;">₹{sr["s1"]:,.2f}</span></div>'
        sr_html += f'<div style="background:#1e293b;padding:8px 16px;border-radius:8px;text-align:center;border:2px solid #6366f1;"><span style="color:#94a3b8;font-size:0.7em;">PIVOT</span><br><span style="color:#a5b4fc;font-weight:700;">₹{sr["pivot"]:,.2f}</span></div>'
        sr_html += f'<div style="background:#064e3b;padding:8px 16px;border-radius:8px;text-align:center;"><span style="color:#94a3b8;font-size:0.7em;">R1</span><br><span style="color:#34d399;font-weight:700;">₹{sr["r1"]:,.2f}</span></div>'
        sr_html += f'<div style="background:#065f46;padding:8px 16px;border-radius:8px;text-align:center;"><span style="color:#94a3b8;font-size:0.7em;">R2</span><br><span style="color:#22c55e;font-weight:700;">₹{sr["r2"]:,.2f}</span></div>'
        sr_html += '</div>'
        st.markdown(sr_html, unsafe_allow_html=True)


# ── TAB 3: OPTION CHAIN ──
with tab_optchain:
    if not sym.get("nse"):
        st.info("Option chain not available for this symbol (no NSE symbol).")
    else:
        st.markdown(f"### 🔗 Option Chain — {selected_symbol} ({sym['nse']})")

        @st.cache_data(ttl=120)
        def fetch_full_option_chain(nse_sym):
            try:
                from nsepython import option_chain
                data = option_chain(nse_sym)
                if data and "records" in data:
                    return data
            except Exception:
                pass
            return None

        with st.spinner("Loading option chain..."):
            oc_data = fetch_full_option_chain(sym["nse"])
        if oc_data is None:
            st.warning("Could not fetch option chain data. Will retry on next refresh.")
        else:
            records = oc_data["records"]
            expiry_dates = records.get("expiryDates", [])
            spot_for_oc = data_ok and spot_price or 0

            if expiry_dates:
                selected_expiry = st.selectbox("Select Expiry", expiry_dates, index=0, key="oc_expiry")
            else:
                selected_expiry = None

            if selected_expiry:
                # Build option chain table
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

                # Find ATM strike
                atm_strike = min(all_strikes, key=lambda s: abs(s - spot_for_oc)) if all_strikes and spot_for_oc > 0 else 0

                # Show only strikes near ATM (10 above, 10 below)
                if atm_strike > 0:
                    sorted_strikes = sorted(all_strikes)
                    atm_idx = sorted_strikes.index(atm_strike) if atm_strike in sorted_strikes else len(sorted_strikes) // 2
                    visible_strikes = set(sorted_strikes[max(0, atm_idx - 10):atm_idx + 11])
                    chain_rows = [r for r in chain_rows if r["strike"] in visible_strikes]

                if chain_rows:
                    # Build HTML table
                    oc_table = '<table style="width:100%;border-collapse:collapse;font-size:0.82em;text-align:center;">'
                    oc_table += '<thead><tr style="background:#1e293b;">'
                    oc_table += '<th style="padding:6px;color:#22c55e;">OI</th>'
                    oc_table += '<th style="padding:6px;color:#22c55e;">OI Chg</th>'
                    oc_table += '<th style="padding:6px;color:#22c55e;">Volume</th>'
                    oc_table += '<th style="padding:6px;color:#22c55e;">IV</th>'
                    oc_table += '<th style="padding:6px;color:#22c55e;">LTP</th>'
                    oc_table += '<th style="padding:6px;color:#fbbf24;font-weight:700;">STRIKE</th>'
                    oc_table += '<th style="padding:6px;color:#ef4444;">LTP</th>'
                    oc_table += '<th style="padding:6px;color:#ef4444;">IV</th>'
                    oc_table += '<th style="padding:6px;color:#ef4444;">Volume</th>'
                    oc_table += '<th style="padding:6px;color:#ef4444;">OI Chg</th>'
                    oc_table += '<th style="padding:6px;color:#ef4444;">OI</th>'
                    oc_table += '</tr>'
                    oc_table += '<tr style="background:#1e293b;"><th colspan="5" style="padding:4px;color:#22c55e;font-size:0.9em;">CALLS</th><th></th><th colspan="5" style="padding:4px;color:#ef4444;font-size:0.9em;">PUTS</th></tr>'
                    oc_table += '</thead><tbody>'

                    for r in chain_rows:
                        is_atm = r["strike"] == atm_strike
                        is_itm_ce = spot_for_oc > 0 and r["strike"] < spot_for_oc  # CE ITM
                        is_itm_pe = spot_for_oc > 0 and r["strike"] > spot_for_oc  # PE ITM
                        row_bg = "#1a1a2e" if is_atm else ""
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

                    if spot_for_oc > 0:
                        st.caption(f"Spot: ₹{spot_for_oc:,.2f} | ATM Strike: {int(atm_strike):,} | Expiry: {selected_expiry}")
                else:
                    st.info("No option chain rows found for this expiry.")


# ── TAB 4: TRADE HISTORY (auto-created) ──
with tab_trades:
    st.markdown("### 🟢 Open Trades (Auto-Created)")
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

            # Manual close option (in case you want to exit early)
            with st.expander(f"🔧 Manually close {t['id']}"):
                exit_p = st.number_input(f"Exit Price", min_value=0.0, value=0.0, step=1.0, format="%.2f", key=f"exit_{t['id']}")
                col_close, col_del = st.columns(2)
                with col_close:
                    if st.button("Close Trade", key=f"close_{t['id']}"):
                        if exit_p > 0:
                            closed = close_trade(t["id"], exit_p)
                            if closed:
                                send_sms_to_all(closed, action="EXIT")
                                st.success(f"Closed. P&L: {'+'if closed['pnl']>=0 else ''}₹{closed['pnl']:,.2f}")
                                st.rerun()
                        else:
                            st.error("Enter exit price")
                with col_del:
                    if st.button("🗑️ Delete", key=f"del_{t['id']}"):
                        delete_trade(t["id"])
                        st.rerun()
    else:
        st.info("No open trades. Signals will auto-create trades and send SMS when they fire.")

    st.markdown("---")
    st.markdown("### 📕 Closed Trades")
    closed_trades = get_closed_trades()
    if closed_trades:
        total_pnl = sum(t.get("pnl", 0) for t in closed_trades)
        sign = "+" if total_pnl >= 0 else ""
        pnl_color = "#22c55e" if total_pnl >= 0 else "#ef4444"
        st.markdown(f'<p style="font-size:1.1em;">Total P&L: <span style="color:{pnl_color};font-weight:700;">{sign}₹{total_pnl:,.2f}</span> ({len(closed_trades)} trades)</p>', unsafe_allow_html=True)

        for t in reversed(closed_trades[-15:]):
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


# ── TAB 5: PORTFOLIO ──
with tab_portfolio:
    st.markdown("### 💰 Portfolio Dashboard")

    port_open = get_open_trades()
    port_closed = get_closed_trades()
    all_trades_count = len(port_open) + len(port_closed)

    # Summary stats
    total_pnl_port = sum(t.get("pnl", 0) for t in port_closed) if port_closed else 0
    wins = [t for t in port_closed if t.get("pnl", 0) > 0]
    losses = [t for t in port_closed if t.get("pnl", 0) <= 0]
    win_rate = (len(wins) / len(port_closed) * 100) if port_closed else 0
    best_trade = max((t.get("pnl", 0) for t in port_closed), default=0) if port_closed else 0
    worst_trade = min((t.get("pnl", 0) for t in port_closed), default=0) if port_closed else 0
    avg_pnl = (total_pnl_port / len(port_closed)) if port_closed else 0

    # Summary cards row
    sc1, sc2, sc3, sc4, sc5, sc6 = st.columns(6)
    pnl_col = "#22c55e" if total_pnl_port >= 0 else "#ef4444"
    pnl_sign = "+" if total_pnl_port >= 0 else ""
    with sc1:
        st.markdown(f'<div class="indicator-card"><h4>TOTAL P&L</h4><div class="value" style="color:{pnl_col};">{pnl_sign}₹{total_pnl_port:,.2f}</div></div>', unsafe_allow_html=True)
    with sc2:
        wr_col = "#22c55e" if win_rate >= 50 else "#ef4444"
        st.markdown(f'<div class="indicator-card"><h4>WIN RATE</h4><div class="value" style="color:{wr_col};">{win_rate:.1f}%</div></div>', unsafe_allow_html=True)
    with sc3:
        st.markdown(f'<div class="indicator-card"><h4>TOTAL TRADES</h4><div class="value">{all_trades_count}</div></div>', unsafe_allow_html=True)
    with sc4:
        st.markdown(f'<div class="indicator-card"><h4>BEST TRADE</h4><div class="value" style="color:#22c55e;">+₹{best_trade:,.2f}</div></div>', unsafe_allow_html=True)
    with sc5:
        st.markdown(f'<div class="indicator-card"><h4>WORST TRADE</h4><div class="value" style="color:#ef4444;">₹{worst_trade:,.2f}</div></div>', unsafe_allow_html=True)
    with sc6:
        avg_col = "#22c55e" if avg_pnl >= 0 else "#ef4444"
        avg_sign = "+" if avg_pnl >= 0 else ""
        st.markdown(f'<div class="indicator-card"><h4>AVG P&L</h4><div class="value" style="color:{avg_col};">{avg_sign}₹{avg_pnl:,.2f}</div></div>', unsafe_allow_html=True)

    st.markdown("---")

    # Open Positions
    st.markdown("#### 🟢 Open Positions")
    if port_open:
        for t in reversed(port_open):
            # Fetch current LTP only during market hours (avoid slow calls when closed)
            current_ltp = None
            if is_market_open():
                t_sym_info = SYMBOLS.get(t["instrument"], {})
                t_nse = t_sym_info.get("nse", "")
                if t_nse:
                    try:
                        current_ltp = get_current_option_ltp(t_nse, t["strike"], t["option_type"], t["expiry"])
                    except Exception:
                        pass

            card_html = f'<div class="trade-card trade-open">'
            card_html += f'<h3>🟢 {t["instrument"]} {int(t["strike"])} {t["option_type"]} ({t["expiry"]})</h3>'
            card_html += f'<div class="detail">Entry: <b>₹{t["entry_price"]:,.2f}</b>'
            if current_ltp is not None:
                unrealized = (current_ltp - t["entry_price"]) * t["quantity"] * t["lot_size"]
                u_col = "#22c55e" if unrealized >= 0 else "#ef4444"
                u_sign = "+" if unrealized >= 0 else ""
                card_html += f' | Current: <b>₹{current_ltp:,.2f}</b>'
                card_html += f'</div>'
                card_html += f'<div class="pnl" style="color:{u_col};">Unrealized P&L: {u_sign}₹{unrealized:,.2f}</div>'
            else:
                card_html += f'</div>'
                card_html += f'<div class="detail" style="color:#6b7280;">Current LTP unavailable</div>'
            card_html += f'<div class="detail" style="color:#6b7280;font-size:0.8em;">{t["created_at"][:16]}</div>'
            card_html += '</div>'
            st.markdown(card_html, unsafe_allow_html=True)
    else:
        st.info("No open positions.")

    st.markdown("---")

    # Cumulative P&L chart (running total)
    st.markdown("#### 📊 Cumulative P&L")
    if port_closed:
        cum_pnl = 0
        cum_data = []
        for t in port_closed:
            cum_pnl += t.get("pnl", 0)
            trade_label = f'{t["instrument"]} {int(t["strike"])}{t["option_type"]}'
            cum_data.append({"Trade": trade_label, "Cumulative P&L": round(cum_pnl, 2)})

        # Build simple bar chart with HTML
        if cum_data:
            max_abs = max(abs(d["Cumulative P&L"]) for d in cum_data) or 1
            chart_html = '<div style="padding:8px;">'
            for i, d in enumerate(cum_data):
                val = d["Cumulative P&L"]
                pct = abs(val) / max_abs * 100
                bar_col = "#22c55e" if val >= 0 else "#ef4444"
                sign_str = "+" if val >= 0 else ""
                chart_html += f'<div style="display:flex;align-items:center;margin:3px 0;gap:8px;">'
                chart_html += f'<span style="color:#94a3b8;font-size:0.75em;min-width:60px;text-align:right;">#{i+1}</span>'
                chart_html += f'<div style="background:{bar_col};height:16px;width:{pct}%;border-radius:3px;min-width:2px;"></div>'
                chart_html += f'<span style="color:{bar_col};font-size:0.8em;font-weight:600;">{sign_str}₹{val:,.2f}</span>'
                chart_html += '</div>'
            chart_html += '</div>'
            st.markdown(chart_html, unsafe_allow_html=True)
    else:
        st.info("No closed trades yet to show P&L chart.")


# ── TAB 6: NEWS + AI ──
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


# ── TAB 7: SMS ADMIN ──
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
