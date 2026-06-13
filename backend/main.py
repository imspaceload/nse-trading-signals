"""
NSE Trading Signals — FastAPI Backend
Wraps all existing Python modules (zerodha_api, indicators, data_fetcher, etc.)
and exposes REST + WebSocket endpoints for the Next.js frontend.
"""
import os
import sys
import asyncio
import concurrent.futures
from typing import List, Optional
from datetime import datetime

import pytz

# ── Path setup: import from parent directory ──────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Load .env from root (same pattern as app.py)
_env_path = os.path.join(_ROOT, ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _ef:
        for _line in _ef:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

import zerodha_api
from config import SYMBOLS
from data_fetcher import get_nse_indices, is_market_open, get_option_chain_nse_direct
from news_scraper import scrape_moneycontrol_news
from sms_sender import get_watchlist, add_to_watchlist, remove_from_watchlist
from indicators import compute_rsi, compute_macd, compute_supertrend, compute_vwap, generate_signal

import pandas as pd
import yfinance as yf

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ─────────────────────────────────────────────────────────────────────────────
IST = pytz.timezone("Asia/Kolkata")

app = FastAPI(title="NSE Trading API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Restore Kite token on startup ──────────────────────────────────────────
@app.on_event("startup")
async def _startup():
    zerodha_api.restore_saved_token()


# ── SECTOR_STOCKS (copied from app.py) ────────────────────────────────────
SECTOR_STOCKS = {
    "Banking 🏦":           ["HDFCBANK","ICICIBANK","SBIN","KOTAKBANK","AXISBANK","INDUSINDBK","BANKBARODA","PNB","CANBK","FEDERALBNK","IDFCFIRSTB","BANDHANBNK"],
    "IT / Tech 💻":         ["TCS","INFY","WIPRO","HCLTECH","TECHM","LTIM","MPHASIS","PERSISTENT","COFORGE","OFSS"],
    "Auto 🚗":              ["TATAMOTORS","MARUTI","M&M","BAJAJ-AUTO","HEROMOTOCO","EICHERMOT","TVSMOTOR","ASHOKLEY","MOTHERSON","BALKRISIND"],
    "Pharma 💊":            ["SUNPHARMA","DRREDDY","CIPLA","DIVISLAB","AUROPHARMA","TORNTPHARM","LUPIN","ALKEM","BIOCON","IPCALAB"],
    "FMCG 🛒":              ["HINDUNILVR","ITC","NESTLEIND","BRITANNIA","MARICO","DABUR","GODREJCP","COLPAL","TATACONSUM","EMAMILTD"],
    "Metal & Mining ⛏":    ["TATASTEEL","HINDALCO","JSWSTEEL","SAIL","VEDL","NMDC","NATIONALUM","HINDCOPPER","APLAPOLLO"],
    "Energy & Oil ⚡":      ["RELIANCE","ONGC","BPCL","IOC","GAIL","PETRONET","MGL","IGL","TATAPOWER","ADANIGREEN"],
    "Infrastructure 🏗":    ["LT","ULTRACEMCO","GRASIM","SHREECEM","ADANIPORTS","RVNL","IRFC","PFC","RECLTD","NTPC"],
    "Telecom 📡":           ["BHARTIARTL","IDEA","INDUSTOWER"],
    "Consumer & Retail 🛍": ["ZOMATO","DMART","TRENT","JUBLFOOD","DEVYANI","SAPPHIRE","NYKAA","INDHOTEL","EIHOTEL","LEMONTRE"],
    "Financial Services 📈":["BAJFINANCE","BAJAJFINSV","HDFCAMC","MUTHOOTFIN","CHOLAFIN","SBICARD","MANAPPURAM","IIFL","M&MFIN"],
}
_SECTOR_UNIVERSE = tuple(sorted({s for stocks in SECTOR_STOCKS.values() for s in stocks}))

# ── Timeframe map ─────────────────────────────────────────────────────────
_TF_YF_MAP = {
    "1m":  ("1d",  "1m"),
    "3m":  ("1d",  "2m"),
    "5m":  ("1d",  "5m"),
    "15m": ("5d",  "15m"),
    "1h":  ("5d",  "60m"),
    "1D":  ("1mo", "1d"),
}

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=20)


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_ohlcv_yf(symbol: str, timeframe: str) -> pd.DataFrame:
    """Fetch OHLCV via yfinance for a single NSE stock."""
    period, interval = _TF_YF_MAP.get(timeframe, ("1d", "5m"))
    try:
        df = yf.Ticker(f"{symbol}.NS").history(period=period, interval=interval)
        if not df.empty:
            return df
    except Exception:
        pass
    return pd.DataFrame()


def _fetch_ohlcv_bulk_yf(symbols: List[str], timeframe: str) -> dict:
    """Bulk yfinance download for a list of NSE symbols."""
    period, interval = _TF_YF_MAP.get(timeframe, ("5d", "15m"))
    tickers = " ".join(f"{s}.NS" for s in symbols)
    try:
        dl = yf.download(tickers, period=period, interval=interval,
                         group_by="ticker", threads=True, progress=False, auto_adjust=True)
        result = {}
        for s in symbols:
            try:
                key = f"{s}.NS"
                if key in dl.columns.get_level_values(0):
                    df = dl[key].dropna()
                    if not df.empty:
                        result[s] = df
            except Exception:
                pass
        return result
    except Exception:
        return {}


def _score_one(sym: str, df: pd.DataFrame) -> Optional[dict]:
    """Compute 5-point signal score for a single symbol (RSI+MACD+ST+VWAP+Vol)."""
    if df is None or df.empty or len(df) < 20:
        return None
    try:
        spot = float(df["Close"].iloc[-1])
        rsi_d  = compute_rsi(df)
        macd_d = compute_macd(df)
        st_d   = compute_supertrend(df)
        vwap_d = compute_vwap(df)

        buy_pts = sell_pts = 0
        rsi_sig  = (rsi_d.get("signal")  or "NEUTRAL") if rsi_d  else "NEUTRAL"
        macd_sig = (macd_d.get("signal") or "NEUTRAL") if macd_d else "NEUTRAL"
        vwap_sig = (vwap_d.get("signal") or "NEUTRAL") if vwap_d else "NEUTRAL"

        if rsi_sig  == "BUY":   buy_pts  += 1
        elif rsi_sig  == "SELL": sell_pts += 1
        if macd_sig == "BUY":   buy_pts  += 1
        elif macd_sig == "SELL": sell_pts += 1
        if st_d:
            if st_d.get("direction") == 1: buy_pts  += 1
            else:                           sell_pts += 1
        if vwap_sig == "BUY":   buy_pts  += 1
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
        return {
            "symbol":     sym,
            "spot":       round(spot, 2),
            "buy_pts":    buy_pts,
            "sell_pts":   sell_pts,
            "score":      max_score,
            "direction":  direction,
            "rsi":        rsi_val,
            "macd":       macd_sig,
            "supertrend": "BULL" if (st_d and st_d.get("direction") == 1) else "BEAR",
            "vwap":       vwap_sig,
            "vol_spike":  vol_spike,
            "day_pct":    day_pct,
        }
    except Exception:
        return None


def _run_scanner(symbols: tuple, timeframe: str, use_kite: bool) -> List[dict]:
    """Run signal scoring on a universe of symbols."""
    if use_kite and zerodha_api.is_connected():
        ohlcv_map = zerodha_api.get_historical_data_bulk(list(symbols), timeframe, max_workers=5)
    else:
        ohlcv_map = _fetch_ohlcv_bulk_yf(list(symbols), timeframe)

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        futs = {ex.submit(_score_one, sym, ohlcv_map.get(sym)): sym for sym in symbols}
        try:
            for fut in concurrent.futures.as_completed(futs, timeout=60):
                try:
                    r = fut.result()
                    if r:
                        results.append(r)
                except Exception:
                    pass
        except concurrent.futures.TimeoutError:
            pass

    results.sort(key=lambda x: (x["score"], x["direction"] == "BUY"), reverse=True)
    return results


# ─────────────────────────────────────────────────────────────────────────────
#  REST ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    kite_ok = zerodha_api.is_connected() if zerodha_api.is_configured() else False
    return {"status": "ok", "kite_connected": kite_ok}


@app.get("/api/indices")
def indices():
    try:
        data = get_nse_indices()
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/quotes")
def quotes(symbols: str = Query(..., description="Comma-separated NSE symbols")):
    """Get Kite quotes for given symbols. Returns {symbol: {ltp, pct, change, open, high, low, volume}}"""
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if not sym_list:
        raise HTTPException(status_code=400, detail="No symbols provided")
    if not zerodha_api.is_connected():
        raise HTTPException(status_code=503, detail="Kite not connected")
    try:
        raw = zerodha_api.get_quotes(sym_list)
        return raw
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chart")
def chart(symbol: str = Query(...), timeframe: str = Query("5m")):
    """Get OHLCV candles for a symbol. Returns list of {time, open, high, low, close, volume}."""
    df = pd.DataFrame()

    if zerodha_api.is_connected():
        try:
            df = zerodha_api.get_historical_data(symbol, timeframe)
        except Exception:
            pass

    if df is None or df.empty:
        df = _fetch_ohlcv_yf(symbol, timeframe)

    if df is None or df.empty:
        return []

    rows = []
    for ts, row in df.iterrows():
        try:
            if timeframe == "1D":
                t = ts.date().isoformat() if hasattr(ts, "date") else str(ts)[:10]
            else:
                t = int(ts.timestamp()) if hasattr(ts, "timestamp") else int(pd.Timestamp(ts).timestamp())
            rows.append({
                "time":   t,
                "open":   round(float(row["Open"]),   2),
                "high":   round(float(row["High"]),   2),
                "low":    round(float(row["Low"]),    2),
                "close":  round(float(row["Close"]),  2),
                "volume": int(row.get("Volume", 0) or 0),
            })
        except Exception:
            continue
    return rows


@app.get("/api/scanner")
def scanner(timeframe: str = Query("15m")):
    """Run signal scoring on all sector universe stocks. Returns sorted list by score."""
    use_kite = zerodha_api.is_connected()
    try:
        results = _run_scanner(_SECTOR_UNIVERSE, timeframe, use_kite)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sector-picks")
def sector_picks(sector: str = Query(...), timeframe: str = Query("15m")):
    """Return top 4 stocks in a sector with signal data."""
    stocks = SECTOR_STOCKS.get(sector)
    if not stocks:
        raise HTTPException(status_code=404, detail=f"Sector '{sector}' not found")

    use_kite = zerodha_api.is_connected()
    try:
        results = _run_scanner(tuple(stocks), timeframe, use_kite)
        return results[:4]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/option-chain")
def option_chain(symbol: str = Query("NIFTY")):
    """Get option chain data for a symbol."""
    # Try Kite first
    if zerodha_api.is_connected():
        try:
            data = zerodha_api.get_option_chain_kite(symbol)
            if data:
                return data
        except Exception:
            pass

    # Fallback: NSE direct
    try:
        data = get_option_chain_nse_direct(symbol)
        if data:
            return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    raise HTTPException(status_code=503, detail="Option chain data unavailable")


@app.get("/api/news")
def news():
    """Get top 10 news items from MoneyControl."""
    try:
        items = scrape_moneycontrol_news()
        return items[:10] if items else []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/watchlist")
def get_wl():
    try:
        return get_watchlist()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class WatchlistAdd(BaseModel):
    symbol: str


@app.post("/api/watchlist")
def add_wl(body: WatchlistAdd):
    sym = body.symbol.strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="Symbol is required")
    result = add_to_watchlist(sym)
    return {"success": result, "symbol": sym}


@app.delete("/api/watchlist/{symbol}")
def remove_wl(symbol: str):
    sym = symbol.strip().upper()
    result = remove_from_watchlist(sym)
    return {"success": result, "symbol": sym}


@app.get("/api/kite/login-url")
def kite_login_url():
    url = zerodha_api.get_login_url()
    if not url:
        raise HTTPException(status_code=503, detail="Kite not configured")
    return {"url": url}


class KiteCallback(BaseModel):
    request_token: str


@app.post("/api/kite/callback")
def kite_callback(body: KiteCallback):
    token = zerodha_api.complete_login(body.request_token)
    if token:
        return {"success": True, "message": "Kite login successful"}
    raise HTTPException(status_code=400, detail="Kite login failed — invalid request token")


# ─────────────────────────────────────────────────────────────────────────────
#  LIVE CHART ENDPOINTS (used by chart iframe to self-update without page reload)
# ─────────────────────────────────────────────────────────────────────────────

# Maps app-key → Kite instrument string for indices
_LIVE_INDEX_MAP = {
    "NIFTY 50":       "NIFTY 50",
    "BANK NIFTY":     "NIFTY BANK",
    "FIN NIFTY":      "NIFTY FIN SERVICE",
    "MIDCAP SELECT":  "NIFTY MID SELECT",
    "INDIA VIX":      "INDIA VIX",
    "SENSEX":         "",  # BSE, not available via NSE Kite segment
}

def _resolve_sym(key: str):
    """Return (kite_sym, yf_sym, is_mcx) for an app-key like 'NIFTY 50' or 'RELIANCE'."""
    conf = SYMBOLS.get(key, {})
    yf = conf.get("yf", f"{key}.NS")
    nse = conf.get("nse", key)
    is_mcx = yf.startswith(("CL=", "NG=", "GC=", "SI="))
    kite_sym = _LIVE_INDEX_MAP.get(key, nse) if not is_mcx else ""
    return kite_sym, yf, is_mcx

def _pivot_from_df(df: pd.DataFrame, tf: str) -> dict:
    """Compute standard pivot points from OHLCV dataframe."""
    try:
        if tf == "1D":
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
                H = float(prev_df["High"].max())
                L = float(prev_df["Low"].min())
                C = float(prev_df["Close"].iloc[-1])
        PP = (H + L + C) / 3
        return {
            "PP": round(PP, 2),
            "R1": round(2*PP - L, 2), "R2": round(PP + H - L, 2),
            "S1": round(2*PP - H, 2), "S2": round(PP - H + L, 2),
        }
    except Exception:
        return {}

_BSE_SYM_MAP = {"SENSEX": "SENSEX"}  # app_key → BSE tradingsymbol

def _kite_quote_result(data: dict) -> dict:
    ltp = float(data["last_price"])
    prev = float(data.get("ohlc", {}).get("close", ltp) or ltp)
    chg  = round(ltp - prev, 2)
    pct  = round(chg / prev * 100, 2) if prev else 0
    return {"price": round(ltp, 2), "pct": pct, "change": chg}

@app.get("/api/live/watchlist")
def live_watchlist(keys: str = Query(..., description="Comma-separated app symbol keys")):
    """Batch LTP+pct for all watchlist symbols. Handles NSE indices, BSE (SENSEX), and MCX."""
    key_list = [k.strip() for k in keys.split(",") if k.strip()]
    result: dict = {}

    nse_map:  dict = {}   # kite_nse_sym → app_key
    nse_syms: list = []
    bse_map:  dict = {}   # kite_bse_sym → app_key
    bse_syms: list = []
    yf_keys:  list = []   # (app_key, yf_sym) for MCX / no-Kite symbols

    for k in key_list:
        if k in _BSE_SYM_MAP:
            bse_map[_BSE_SYM_MAP[k]] = k
            bse_syms.append(_BSE_SYM_MAP[k])
        else:
            kite_sym, yf_sym, is_mcx = _resolve_sym(k)
            if kite_sym and not is_mcx and zerodha_api.is_connected():
                nse_map[kite_sym] = k
                nse_syms.append(kite_sym)
            elif yf_sym:
                yf_keys.append((k, yf_sym))

    # NSE batch (indices + equities)
    if nse_syms and zerodha_api.is_connected():
        try:
            raw = zerodha_api.get_quotes(nse_syms)
            for ksym, data in raw.items():
                app_key = nse_map.get(ksym)
                if app_key:
                    result[app_key] = _kite_quote_result(data)
        except Exception:
            pass

    # BSE batch (SENSEX)
    if bse_syms and zerodha_api.is_connected():
        try:
            raw = zerodha_api.get_quotes(bse_syms, exchange="BSE")
            for ksym, data in raw.items():
                app_key = bse_map.get(ksym)
                if app_key:
                    result[app_key] = _kite_quote_result(data)
        except Exception:
            pass

    # yfinance for MCX commodities and anything Kite can't serve
    for app_key, yf_sym in yf_keys:
        try:
            fi = yf.Ticker(yf_sym).fast_info
            ltp = getattr(fi, "last_price", None) or getattr(fi, "regularMarketPrice", None)
            if ltp:
                chg  = float(getattr(fi, "regularMarketChange", 0) or 0)
                prev = float(ltp) - chg
                pct  = round(chg / prev * 100, 2) if prev else 0
                result[app_key] = {"price": round(float(ltp), 2), "pct": pct, "change": round(chg, 2)}
        except Exception:
            pass

    return result


@app.get("/api/live/ltp")
def live_ltp(key: str = Query(..., description="App symbol key e.g. 'NIFTY 50' or 'RELIANCE'")):
    """Live last-traded price for chart JS polling. Sub-second Kite data when connected."""
    # BSE symbols (SENSEX)
    if key in _BSE_SYM_MAP and zerodha_api.is_connected():
        try:
            raw = zerodha_api.get_quotes([_BSE_SYM_MAP[key]], exchange="BSE")
            bse_sym = _BSE_SYM_MAP[key]
            if bse_sym in raw:
                r = _kite_quote_result(raw[bse_sym])
                return {"price": r["price"], "pct": r["pct"]}
        except Exception:
            pass

    kite_sym, yf_sym, is_mcx = _resolve_sym(key)

    if kite_sym and zerodha_api.is_connected():
        try:
            raw = zerodha_api.get_quotes([kite_sym])
            if kite_sym in raw:
                d = raw[kite_sym]
                return {"price": round(float(d["last_price"]), 2), "pct": round(float(d.get("pct", 0)), 2)}
        except Exception:
            pass

    # yfinance fallback
    try:
        import yfinance as yf
        fi = yf.Ticker(yf_sym).fast_info
        ltp = getattr(fi, "last_price", None) or getattr(fi, "regularMarketPrice", None)
        if ltp:
            pct = getattr(fi, "regularMarketChangePercent", 0) or 0
            return {"price": round(float(ltp), 2), "pct": round(float(pct), 2)}
    except Exception:
        pass

    return {"price": 0, "pct": 0}


@app.get("/api/live/candles")
def live_candles(
    key: str = Query(..., description="App symbol key e.g. 'NIFTY 50' or 'RELIANCE'"),
    tf:  str = Query("5m", description="Timeframe: 1m 3m 5m 15m 1h 1D"),
):
    """
    OHLCV candles + pivot levels for a symbol. Chart iframe polls this every 30s.
    Returns IST-aligned UNIX timestamps for intraday, ISO date strings for daily.
    """
    kite_sym, yf_sym, is_mcx = _resolve_sym(key)
    df = pd.DataFrame()

    # Try Kite historical data (uses nse symbol or index token)
    if not is_mcx and zerodha_api.is_connected():
        try:
            nse = SYMBOLS.get(key, {}).get("nse", key)
            df = zerodha_api.get_historical_data(nse, tf)
        except Exception:
            pass

    # Fallback: yfinance
    if df is None or df.empty:
        _tf_yf = {"1m":("5d","1m"),"3m":("5d","2m"),"5m":("5d","5m"),"15m":("5d","15m"),"1h":("5d","60m"),"1D":("1mo","1d")}
        period, interval = _tf_yf.get(tf, ("5d","5m"))
        try:
            import yfinance as yf
            df = yf.Ticker(yf_sym).history(period=period, interval=interval)
        except Exception:
            pass

    if df is None or df.empty:
        return {"candles": [], "pivots": {}}

    candles = []
    for ts, row in df.iterrows():
        try:
            if tf == "1D":
                t = ts.date().isoformat() if hasattr(ts, "date") else str(ts)[:10]
            else:
                _utc = int(ts.timestamp()) if hasattr(ts, "timestamp") else int(pd.Timestamp(ts).timestamp())
                t = _utc + 19800  # shift UTC → IST for Lightweight Charts display
            candles.append({
                "time":  t,
                "open":  round(float(row["Open"]),  2),
                "high":  round(float(row["High"]),  2),
                "low":   round(float(row["Low"]),   2),
                "close": round(float(row["Close"]), 2),
            })
        except Exception:
            continue

    pivots = _pivot_from_df(df, tf)
    return {"candles": candles, "pivots": pivots}


# ─────────────────────────────────────────────────────────────────────────────
#  WEBSOCKET — real-time ticker
# ─────────────────────────────────────────────────────────────────────────────

@app.websocket("/ws/ticker")
async def ws_ticker(websocket: WebSocket, symbols: str = Query(default="")):
    await websocket.accept()

    sym_list = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else []

    loop = asyncio.get_event_loop()

    def _get_quotes_sync(syms: List[str]) -> dict:
        if not syms or not zerodha_api.is_connected():
            return {}
        try:
            raw = zerodha_api.get_quotes(syms)
            result = {}
            for sym, data in raw.items():
                result[sym] = {
                    "ltp":    data.get("last_price", 0),
                    "pct":    data.get("pct", 0),
                    "change": data.get("change", 0),
                }
            return result
        except Exception:
            return {}

    def _get_quotes_yf_fallback(syms: List[str]) -> dict:
        """Fallback: fetch last price from yfinance fast_info for each symbol."""
        result = {}
        for sym in syms:
            try:
                fi = yf.Ticker(f"{sym}.NS").fast_info
                ltp = getattr(fi, "last_price", None) or getattr(fi, "regularMarketPrice", None)
                prev = getattr(fi, "previous_close", None) or getattr(fi, "regularMarketPreviousClose", None)
                if ltp and ltp > 0:
                    change = round(ltp - (prev or ltp), 2) if prev else 0
                    pct = round(change / prev * 100, 2) if prev and prev > 0 else 0
                    result[sym] = {"ltp": round(ltp, 2), "pct": pct, "change": change}
            except Exception:
                pass
        return result

    try:
        # Send initial snapshot
        active_syms = sym_list if sym_list else get_watchlist()
        if active_syms:
            initial = await loop.run_in_executor(
                _executor, _get_quotes_sync, active_syms
            )
            if not initial:
                initial = await loop.run_in_executor(
                    _executor, _get_quotes_yf_fallback, active_syms[:10]
                )
            if initial:
                await websocket.send_json(initial)

        # Stream updates every 2 seconds
        while True:
            await asyncio.sleep(2)
            current_syms = sym_list if sym_list else get_watchlist()
            if not current_syms:
                continue
            quotes_data = await loop.run_in_executor(
                _executor, _get_quotes_sync, current_syms
            )
            if not quotes_data:
                quotes_data = await loop.run_in_executor(
                    _executor, _get_quotes_yf_fallback, current_syms[:10]
                )
            if quotes_data:
                await websocket.send_json(quotes_data)

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
