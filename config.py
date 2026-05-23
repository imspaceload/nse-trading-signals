import os

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-6"

# Each symbol has:
#   yf   - Yahoo Finance ticker (for data fetching / indicators)
#   nse  - NSE symbol (for option chain via nsepython)
#   tv   - TradingView widget symbol (for live chart)
SYMBOLS = {
    # ── Indices ──
    "NIFTY 50":         {"yf": "^NSEI",           "nse": "NIFTY",       "tv": "NSE:NIFTY"},
    "BANK NIFTY":       {"yf": "^NSEBANK",        "nse": "BANKNIFTY",   "tv": "NSE:BANKNIFTY"},
    "SENSEX":           {"yf": "^BSESN",          "nse": "",            "tv": "BSE:SENSEX"},
    # ── Commodities ──
    "MCX CRUDE OIL":    {"yf": "CL=F",            "nse": "",            "tv": "MCX:CRUDEOIL1!"},
    "MCX NATURAL GAS":  {"yf": "NG=F",            "nse": "",            "tv": "MCX:NATURALGAS1!"},
    "MCX GOLD":         {"yf": "GC=F",            "nse": "",            "tv": "MCX:GOLD1!"},
    "MCX SILVER":       {"yf": "SI=F",            "nse": "",            "tv": "MCX:SILVER1!"},
    # ── NIFTY 50 Stocks ──
    "RELIANCE":         {"yf": "RELIANCE.NS",     "nse": "RELIANCE",    "tv": "NSE:RELIANCE"},
    "TCS":              {"yf": "TCS.NS",          "nse": "TCS",         "tv": "NSE:TCS"},
    "INFOSYS":          {"yf": "INFY.NS",         "nse": "INFY",        "tv": "NSE:INFY"},
    "HDFC BANK":        {"yf": "HDFCBANK.NS",     "nse": "HDFCBANK",    "tv": "NSE:HDFCBANK"},
    "ICICI BANK":       {"yf": "ICICIBANK.NS",    "nse": "ICICIBANK",   "tv": "NSE:ICICIBANK"},
    "SBIN":             {"yf": "SBIN.NS",         "nse": "SBIN",        "tv": "NSE:SBIN"},
    "TATAMOTORS":       {"yf": "TATAMOTORS.NS",   "nse": "TATAMOTORS",  "tv": "NSE:TATAMOTORS"},
    "ITC":              {"yf": "ITC.NS",          "nse": "ITC",         "tv": "NSE:ITC"},
    "WIPRO":            {"yf": "WIPRO.NS",        "nse": "WIPRO",       "tv": "NSE:WIPRO"},
    "ADANIENT":         {"yf": "ADANIENT.NS",     "nse": "ADANIENT",    "tv": "NSE:ADANIENT"},
    "BHARTIARTL":       {"yf": "BHARTIARTL.NS",   "nse": "BHARTIARTL",  "tv": "NSE:BHARTIARTL"},
    "HCLTECH":          {"yf": "HCLTECH.NS",      "nse": "HCLTECH",     "tv": "NSE:HCLTECH"},
    "KOTAKBANK":        {"yf": "KOTAKBANK.NS",    "nse": "KOTAKBANK",   "tv": "NSE:KOTAKBANK"},
    "LT":               {"yf": "LT.NS",           "nse": "LT",          "tv": "NSE:LT"},
    "MARUTI":           {"yf": "MARUTI.NS",       "nse": "MARUTI",      "tv": "NSE:MARUTI"},
    "SUNPHARMA":        {"yf": "SUNPHARMA.NS",    "nse": "SUNPHARMA",   "tv": "NSE:SUNPHARMA"},
    "AXISBANK":         {"yf": "AXISBANK.NS",     "nse": "AXISBANK",    "tv": "NSE:AXISBANK"},
    "BAJFINANCE":       {"yf": "BAJFINANCE.NS",   "nse": "BAJFINANCE",  "tv": "NSE:BAJFINANCE"},
    "BAJAJFINSV":       {"yf": "BAJAJFINSV.NS",   "nse": "BAJAJFINSV",  "tv": "NSE:BAJAJFINSV"},
    "TITAN":            {"yf": "TITAN.NS",        "nse": "TITAN",       "tv": "NSE:TITAN"},
    "ASIANPAINT":       {"yf": "ASIANPAINT.NS",   "nse": "ASIANPAINT",  "tv": "NSE:ASIANPAINT"},
    "NESTLEIND":        {"yf": "NESTLEIND.NS",    "nse": "NESTLEIND",   "tv": "NSE:NESTLEIND"},
    "ULTRACEMCO":       {"yf": "ULTRACEMCO.NS",   "nse": "ULTRACEMCO",  "tv": "NSE:ULTRACEMCO"},
    "POWERGRID":        {"yf": "POWERGRID.NS",    "nse": "POWERGRID",   "tv": "NSE:POWERGRID"},
    "NTPC":             {"yf": "NTPC.NS",         "nse": "NTPC",        "tv": "NSE:NTPC"},
    "ONGC":             {"yf": "ONGC.NS",         "nse": "ONGC",        "tv": "NSE:ONGC"},
    "JSWSTEEL":         {"yf": "JSWSTEEL.NS",     "nse": "JSWSTEEL",    "tv": "NSE:JSWSTEEL"},
    "TATASTEEL":        {"yf": "TATASTEEL.NS",    "nse": "TATASTEEL",   "tv": "NSE:TATASTEEL"},
    "TECHM":            {"yf": "TECHM.NS",        "nse": "TECHM",       "tv": "NSE:TECHM"},
    "HINDALCO":         {"yf": "HINDALCO.NS",     "nse": "HINDALCO",    "tv": "NSE:HINDALCO"},
    "INDUSINDBK":       {"yf": "INDUSINDBK.NS",   "nse": "INDUSINDBK",  "tv": "NSE:INDUSINDBK"},
    "DIVISLAB":         {"yf": "DIVISLAB.NS",     "nse": "DIVISLAB",    "tv": "NSE:DIVISLAB"},
    "DRREDDY":          {"yf": "DRREDDY.NS",      "nse": "DRREDDY",     "tv": "NSE:DRREDDY"},
    "CIPLA":            {"yf": "CIPLA.NS",        "nse": "CIPLA",       "tv": "NSE:CIPLA"},
    "APOLLOHOSP":       {"yf": "APOLLOHOSP.NS",   "nse": "APOLLOHOSP",  "tv": "NSE:APOLLOHOSP"},
    "EICHERMOT":        {"yf": "EICHERMOT.NS",    "nse": "EICHERMOT",   "tv": "NSE:EICHERMOT"},
    "HEROMOTOCO":       {"yf": "HEROMOTOCO.NS",   "nse": "HEROMOTOCO",  "tv": "NSE:HEROMOTOCO"},
    "M&M":              {"yf": "M&M.NS",          "nse": "M&M",         "tv": "NSE:M_M"},
    "TATACONSUM":       {"yf": "TATACONSUM.NS",   "nse": "TATACONSUM",  "tv": "NSE:TATACONSUM"},
    "LTIM":             {"yf": "LTIM.NS",         "nse": "LTIM",        "tv": "NSE:LTIM"},
    "COALINDIA":        {"yf": "COALINDIA.NS",    "nse": "COALINDIA",   "tv": "NSE:COALINDIA"},
    "BPCL":             {"yf": "BPCL.NS",         "nse": "BPCL",        "tv": "NSE:BPCL"},
    "GRASIM":           {"yf": "GRASIM.NS",       "nse": "GRASIM",      "tv": "NSE:GRASIM"},
    "HDFCLIFE":         {"yf": "HDFCLIFE.NS",     "nse": "HDFCLIFE",    "tv": "NSE:HDFCLIFE"},
    "SBILIFE":          {"yf": "SBILIFE.NS",      "nse": "SBILIFE",     "tv": "NSE:SBILIFE"},
    "BAJAJ-AUTO":       {"yf": "BAJAJ-AUTO.NS",   "nse": "BAJAJ-AUTO",  "tv": "NSE:BAJAJ_AUTO"},
    "BRITANNIA":        {"yf": "BRITANNIA.NS",    "nse": "BRITANNIA",   "tv": "NSE:BRITANNIA"},
    "SHRIRAMFIN":       {"yf": "SHRIRAMFIN.NS",   "nse": "SHRIRAMFIN",  "tv": "NSE:SHRIRAMFIN"},
}

MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 15
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 15

REFRESH_INTERVAL_SECONDS = 150

RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

SUPERTREND_PERIOD = 10
SUPERTREND_MULTIPLIER = 3.0

STOP_LOSS_PCT = 0.3
TARGET_PCT = 1.0

MIN_INDICATORS_FOR_SIGNAL = 3

MONEYCONTROL_URL = "https://www.moneycontrol.com/news/business/markets/"
NEWS_COUNT = 5

# Email Alert Settings (Gmail SMTP)
# To set up: Go to Google Account → Security → 2-Step Verification → App Passwords
# Generate a 16-char app password and put it below
EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")        # your Gmail address
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")     # Gmail App Password (16 chars)
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER", "")     # client's email to receive alerts

# Fast2SMS Settings
FAST2SMS_API_KEY = os.environ.get("FAST2SMS_API_KEY", "")  # https://www.fast2sms.com

# Supabase Settings (persistent storage for subscribers + SMS log)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
