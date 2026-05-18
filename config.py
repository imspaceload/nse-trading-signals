import os

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-6"

# Each symbol has:
#   yf   - Yahoo Finance ticker (for data fetching / indicators)
#   nse  - NSE symbol (for option chain via nsepython)
#   tv   - TradingView widget symbol (for live chart)
SYMBOLS = {
    "NIFTY 50":         {"yf": "^NSEI",           "nse": "NIFTY",       "tv": "NSE:NIFTY"},
    "BANK NIFTY":       {"yf": "^NSEBANK",        "nse": "BANKNIFTY",   "tv": "NSE:BANKNIFTY"},
    "SENSEX":           {"yf": "^BSESN",          "nse": "",            "tv": "BSE:SENSEX"},
    "MCX CRUDE OIL":    {"yf": "CL=F",            "nse": "",            "tv": "MCX:CRUDEOIL1!"},
    "MCX NATURAL GAS":  {"yf": "NG=F",            "nse": "",            "tv": "MCX:NATURALGAS1!"},
    "MCX GOLD":         {"yf": "GC=F",            "nse": "",            "tv": "MCX:GOLD1!"},
    "MCX SILVER":       {"yf": "SI=F",            "nse": "",            "tv": "MCX:SILVER1!"},
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
