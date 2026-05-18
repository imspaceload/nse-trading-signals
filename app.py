import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
from datetime import datetime
import pytz
import concurrent.futures
import pandas as pd
import json

from config import (
    REFRESH_INTERVAL_SECONDS, RSI_PERIOD, RSI_OVERBOUGHT, RSI_OVERSOLD,
    SYMBOLS, STOP_LOSS_PCT, TARGET_PCT,
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

IST = pytz.timezone("Asia/Kolkata")

st.set_page_config(page_title="NSE Trading Signals", page_icon="📊", layout="wide")

# Auto-refresh: 30 sec during market hours, 5 min when closed
_refresh_ms = 30_000 if is_market_open() else 300_000
st_autorefresh(interval=_refresh_ms, limit=0, key="live_refresh")

st.markdown("""
<style>
    .block-container { padding-top: 1rem; max-width: 100%; }

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

    .alert-banner { animation: pulse 2s infinite; }
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.7; }
    }
</style>
""", unsafe_allow_html=True)

# ── Sidebar ──
with st.sidebar:
    st.markdown("## ⚙️ Settings")

    selected_symbol = st.selectbox("Select Stock / Index", list(SYMBOLS.keys()), index=0)
    sym = SYMBOLS[selected_symbol]

    custom_symbol = st.text_input("Or enter custom TradingView symbol", "", placeholder="e.g. NSE:BAJFINANCE")
    if custom_symbol.strip():
        custom_upper = custom_symbol.strip().upper()
        # Parse exchange:symbol format
        if ":" in custom_upper:
            parts = custom_upper.split(":", 1)
            exchange = parts[0]
            ticker = parts[1]
        else:
            exchange = "NSE"
            ticker = custom_upper
            custom_upper = f"NSE:{ticker}"
        sym = {"yf": f"{ticker}.NS", "nse": ticker, "tv": custom_upper}
        selected_symbol = custom_upper

    chart_period = st.selectbox("Chart Period", ["1d", "5d", "1mo"], index=1)
    chart_interval = st.selectbox("Interval", ["1m", "5m", "15m", "30m", "1h"], index=1)

    if st.button("🔄 Refresh Now", use_container_width=True):
        st.cache_data.clear()

    st.divider()
    now = datetime.now(IST)
    if is_market_open():
        st.success("🟢 Market Open — Live")
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
    st.caption("✅ Live TradingView chart with indicators")
    st.caption("✅ Auto-refreshes every 30s during market")
    st.caption("✅ Sound + email alert on BUY/SELL")
    st.caption("✅ Shows exact option to buy")
    st.caption(f"✅ SL: {STOP_LOSS_PCT}% | Target: {TARGET_PCT}%")


# ── Data Fetching ──
@st.cache_data(ttl=30)
def fetch_data(yf_symbol, nse_symbol, period, interval):
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        price_future = executor.submit(get_spot_price, yf_symbol)
        df_future = executor.submit(get_intraday_data, yf_symbol, period, interval)
        oi_future = executor.submit(get_option_chain_data, nse_symbol) if nse_symbol else None

        spot = price_future.result(timeout=30)
        df = df_future.result(timeout=30)
        try:
            oi = oi_future.result(timeout=20) if oi_future else None
        except Exception:
            oi = None
    return spot, df, oi

@st.cache_data(ttl=REFRESH_INTERVAL_SECONDS)
def fetch_news():
    return scrape_moneycontrol_news()

def compute_for_symbol(yf_sym, nse_sym, period, interval):
    """Fetch data and compute all indicators + signal for a symbol."""
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

# Fetch selected symbol data
with st.spinner(f"Loading {selected_symbol} data..."):
    inst_data = compute_for_symbol(sym["yf"], sym["nse"], chart_period, chart_interval)
    news = fetch_news()

if not inst_data:
    st.error(f"Could not fetch data for {selected_symbol}.")
    st.stop()

prices_dict = {
    "nifty": inst_data["spot"] if sym["nse"] == "NIFTY" else None,
    "banknifty": inst_data["spot"] if sym["nse"] == "BANKNIFTY" else None,
}
with st.spinner("AI analyzing..."):
    analysis = analyze_market(
        prices_dict, inst_data["signal"], inst_data["rsi"], inst_data["macd"],
        inst_data["supertrend"], inst_data["vwap"], inst_data["oi"], news,
    )


# ══════════════════════════════════════════
#  BROWSER SOUND ALERT + EMAIL
# ══════════════════════════════════════════

action = inst_data["signal"]["action"]
alert_key = f"last_signal_{selected_symbol}"
last_a = st.session_state.get(alert_key, None)
if action in ("BUY", "SELL") and action != last_a:
    st.session_state[alert_key] = action
    alert_msg = f"{action} {selected_symbol} @₹{inst_data['spot']:,.0f}"

    # Browser sound + push notification
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

    # Send email alert to client
    if email_on and sender and app_pwd and receiver:
        email_ok = send_signal_email(
            sender, app_pwd, receiver,
            selected_symbol, inst_data["signal"], inst_data["option_rec"],
        )
        if email_ok:
            st.toast(f"📧 Email sent to {receiver}!", icon="✅")
        else:
            st.toast("📧 Email failed — check credentials", icon="❌")

elif action == "HOLD":
    st.session_state[alert_key] = "HOLD"


# ══════════════════════════════════════════
#  RENDER SELECTED INSTRUMENT
# ══════════════════════════════════════════

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

# ── Header ──
day_change = df["Close"].iloc[-1] - df["Open"].iloc[0]
day_pct = (day_change / df["Open"].iloc[0]) * 100
color = "#22c55e" if day_change >= 0 else "#ef4444"
arrow = "▲" if day_change >= 0 else "▼"

st.markdown(f"## {selected_symbol} — ₹{spot_price:,.2f}")
st.markdown(f'<span style="color:{color};font-size:1.1em;font-weight:600;">{arrow} ₹{abs(day_change):,.2f} ({day_pct:+.2f}%)</span> &nbsp; <span style="color:#6b7280;">H: ₹{df["High"].max():,.2f} &nbsp; L: ₹{df["Low"].min():,.2f}</span>', unsafe_allow_html=True)

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


# ══════════════════════════════════════════
#  TRADINGVIEW LIVE CHART (iframe embed)
# ══════════════════════════════════════════

tv_symbol = sym["tv"]
tv_interval_map = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60"}
tv_interval = tv_interval_map.get(chart_interval, "5")

# URL-encode the symbol (e.g. NSE:NIFTY -> NSE%3ANIFTY)
tv_symbol_enc = tv_symbol.replace(":", "%3A").replace("!", "%21")

tv_iframe = f"""
<div style="width:100%;height:650px;border-radius:8px;overflow:hidden;">
<iframe
  src="https://s.tradingview.com/widgetembed/?frameElementId=tv_embed&symbol={tv_symbol_enc}&interval={tv_interval}&hidesidetoolbar=0&symboledit=1&saveimage=1&toolbarbg=0e1117&studies=RSI%40tv-basicstudies%1FMACD%40tv-basicstudies%1FSuperTrend%40tv-basicstudies%1FVWAP%40tv-basicstudies&theme=dark&style=1&timezone=Asia%2FKolkata&studies_overrides=%7B%7D&overrides=%7B%7D&enabled_features=%5B%5D&disabled_features=%5B%5D&locale=in&utm_source=localhost&utm_medium=widget_new&utm_campaign=chart"
  style="width:100%;height:100%;border:none;"
  allowtransparency="true"
  scrolling="no"
  allowfullscreen>
</iframe>
</div>
"""

components.html(tv_iframe, height=670, scrolling=False)


# ══════════════════════════════════════════
#  INDICATOR CARDS
# ══════════════════════════════════════════

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


# ══════════════════════════════════════════
#  SIGNAL HISTORY TABLE
# ══════════════════════════════════════════

if all_signals:
    st.markdown(f"#### 📋 {selected_symbol} Signal History")
    rows = ""
    for s in reversed(all_signals[-8:]):
        ts = s["index"].strftime("%d %b %H:%M") if hasattr(s["index"], "strftime") else str(s["index"])
        ac = "#26a69a" if s["action"] == "BUY" else "#ef5350"
        opt_label = "Buy CE" if s["action"] == "BUY" else "Buy PE"
        rows += f'<tr><td>{ts}</td><td><span style="color:{ac};font-weight:700;">{"▲" if s["action"]=="BUY" else "▼"} {s["action"]}</span></td><td>{opt_label}</td><td>₹{s["price"]:,.2f}</td><td>₹{s["sl"]:,.2f}</td><td>₹{s["target"]:,.2f}</td></tr>'
    st.markdown(f'<table class="signal-table"><thead><tr><th>Time</th><th>Signal</th><th>Option</th><th>Entry</th><th>SL</th><th>Target</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)


# ══════════════════════════════════════════
#  NEWS + CLAUDE ANALYSIS
# ══════════════════════════════════════════

st.markdown("---")
nc, ac = st.columns([3, 2])

with nc:
    st.markdown("### Market News")
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

with ac:
    st.markdown("### 🤖 Claude Analysis")
    st.markdown(f'<div class="analysis-box"><p style="color:#e5e7eb;line-height:1.7;font-size:0.95em;">{analysis}</p></div>', unsafe_allow_html=True)

st.markdown("---")
st.caption("⚠️ For educational purposes only. Not financial advice. Always use stop loss.")
