"""
Data fetcher with robust NSE India API session management + Yahoo Finance fallbacks.
"""
from typing import Optional, List
import concurrent.futures
import threading
import time

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import pytz
import requests

from config import (
    MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE,
    MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE,
)

IST = pytz.timezone("Asia/Kolkata")

# ═══════════════════════════════════════════════
#  NSE Session Management (thread-safe singleton)
# ═══════════════════════════════════════════════
_nse_lock = threading.Lock()
_nse_session: Optional[requests.Session] = None
_nse_session_at: float = 0
_NSE_TTL = 1500  # refresh every 25 min

_NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/",
    "sec-fetch-site": "same-origin",
    "sec-fetch-mode": "cors",
    "sec-fetch-dest": "empty",
}


def _build_nse_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_NSE_HEADERS)
    for url in [
        "https://www.nseindia.com",
        "https://www.nseindia.com/market-data/live-equity-market",
    ]:
        try:
            s.get(url, timeout=12)
            time.sleep(0.4)
        except Exception:
            pass
    return s


def _get_nse_session() -> requests.Session:
    global _nse_session, _nse_session_at
    with _nse_lock:
        if _nse_session is None or (time.time() - _nse_session_at) > _NSE_TTL:
            _nse_session = _build_nse_session()
            _nse_session_at = time.time()
        return _nse_session


def _nse_fetch(url: str, timeout: int = 12) -> Optional[dict]:
    """Fetch from NSE API with auto-retry on session expiry."""
    global _nse_session
    for attempt in range(2):
        try:
            s = _get_nse_session()
            r = s.get(url, headers={"Referer": "https://www.nseindia.com/"}, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == 0:
                with _nse_lock:
                    _nse_session = None  # force rebuild on next call
                time.sleep(1)
    return None


# ═══════════════════════════════════════════════
#  Market Status
# ═══════════════════════════════════════════════

def is_market_open() -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    mo = now.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0)
    mc = now.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0, microsecond=0)
    return mo <= now <= mc


def get_market_opens_in() -> str:
    """Return human-readable time until next market open."""
    now = datetime.now(IST)
    # Next weekday open
    days_ahead = 0
    candidate = now
    for _ in range(7):
        candidate = now + timedelta(days=days_ahead)
        if candidate.weekday() < 5:
            open_dt = candidate.replace(
                hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0
            )
            if open_dt > now:
                diff = open_dt - now
                h = diff.seconds // 3600
                m = (diff.seconds % 3600) // 60
                return f"{h}h {m}m"
        days_ahead += 1
    return "--"


# ═══════════════════════════════════════════════
#  NSE Index Data
# ═══════════════════════════════════════════════

_NSE_INDEX_ALIASES = {
    # NSE API name → our key
    "NIFTY 50": "NIFTY 50",
    "NIFTY BANK": "BANK NIFTY",
    "NIFTY FIN SERVICE": "FIN NIFTY",
    "Nifty Financial Services": "FIN NIFTY",
    "NIFTY FINANCIAL SERVICES": "FIN NIFTY",
    "NIFTY MIDCAP SELECT": "MIDCAP SELECT",
    "NIFTY MIDCAP 50": "MIDCAP SELECT",
    "NIFTY SMALLCAP 100": "SMALLCAP",
    "INDIA VIX": "INDIA VIX",
}


def get_nse_indices() -> dict:
    """
    Fetch all NSE indices from NSE API.
    Returns dict keyed by our short name:
      {"NIFTY 50": {"price": 24849.84, "change": 182.19, "pct": 0.74, "open": ..., "high": ..., "low": ...}, ...}
    """
    data = _nse_fetch("https://www.nseindia.com/api/allIndices", timeout=10)
    if not data:
        return {}
    result = {}
    for item in data.get("data", []):
        raw_name = item.get("index", "")
        key = _NSE_INDEX_ALIASES.get(raw_name, raw_name)
        result[key] = {
            "price": item.get("last", 0),
            "change": round(item.get("variation", 0), 2),
            "pct": round(item.get("percentChange", 0), 2),
            "open": item.get("open", 0),
            "high": item.get("dayHigh", item.get("high", 0)),
            "low": item.get("dayLow", item.get("low", 0)),
        }
        # Also store by raw name for fallback lookups
        if raw_name != key:
            result[raw_name] = result[key]
    return result


def get_nse_quote(symbol_nse: str) -> Optional[dict]:
    """Get full quote for an NSE equity symbol."""
    data = _nse_fetch(
        f"https://www.nseindia.com/api/quote-equity?symbol={symbol_nse.upper()}", timeout=10
    )
    return data


# ═══════════════════════════════════════════════
#  Global Market Cues
# ═══════════════════════════════════════════════

def get_global_cues() -> dict:
    """
    Fetch global market cues from Yahoo Finance.
    Returns:
      {"sgx_nifty": {...}, "dow_futures": {...}, "brent": {...}, "usdinr": {...}}
    Each value: {"price": float, "change": float, "pct": float} or None
    """
    yf_map = {
        "sgx_nifty":   "^NSEI",      # NSE Nifty as SGX proxy
        "dow_futures": "YM=F",
        "brent":       "BZ=F",
        "usdinr":      "USDINR=X",
    }

    def _fetch_one(key, sym):
        try:
            t = yf.Ticker(sym)
            fi = t.fast_info
            price = fi.get("lastPrice") or fi.get("regularMarketPrice")
            prev  = fi.get("previousClose") or fi.get("regularMarketPreviousClose")
            if price and price > 0:
                change = round(float(price) - float(prev), 2) if prev else 0
                pct    = round(change / float(prev) * 100, 2) if prev else 0
                return key, {"price": round(float(price), 2), "change": change, "pct": pct}
        except Exception:
            pass
        return key, None

    result = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(_fetch_one, k, v) for k, v in yf_map.items()]
        for f in concurrent.futures.as_completed(futs, timeout=10):
            try:
                k, v = f.result()
                result[k] = v
            except Exception:
                pass
    return result


# ═══════════════════════════════════════════════
#  Spot Price
# ═══════════════════════════════════════════════

_NSE_INDEX_LOOKUP = {
    "NIFTY":      "NIFTY 50",
    "BANKNIFTY":  "BANK NIFTY",
    "FINNIFTY":   "FIN NIFTY",
    "MIDCPNIFTY": "MIDCAP SELECT",
}


def get_spot_price(symbol: str, nse_symbol: str = None) -> Optional[float]:
    """
    Fetch latest price.
    Priority: NSE API (for indices/equities) → Yahoo Finance fast_info → history fallback.
    """
    # 1. NSE index endpoint (most reliable for indices)
    if nse_symbol:
        nse_sym_upper = nse_symbol.strip().upper()
        if nse_sym_upper in _NSE_INDEX_LOOKUP:
            try:
                data = _nse_fetch("https://www.nseindia.com/api/allIndices", timeout=8)
                if data:
                    target = _NSE_INDEX_LOOKUP[nse_sym_upper]
                    for item in data.get("data", []):
                        if _NSE_INDEX_ALIASES.get(item.get("index", ""), item.get("index", "")) == target:
                            p = item.get("last")
                            if p and p > 0:
                                return round(float(p), 2)
            except Exception:
                pass

        # 2. NSE equity quote
        if nse_sym_upper not in _NSE_INDEX_LOOKUP:
            try:
                data = get_nse_quote(nse_sym_upper)
                if data:
                    p = data.get("priceInfo", {}).get("lastPrice")
                    if p and float(p) > 0:
                        return round(float(p), 2)
            except Exception:
                pass

    # 3. Yahoo Finance fast_info
    try:
        t = yf.Ticker(symbol)
        price = t.fast_info.get("lastPrice") or t.fast_info.get("regularMarketPrice")
        if price and float(price) > 0:
            return round(float(price), 2)
    except Exception:
        pass

    # 4. Yahoo Finance history (last resort)
    try:
        t = yf.Ticker(symbol)
        df = t.history(period="2d", interval="5m")
        if not df.empty:
            return round(float(df["Close"].iloc[-1]), 2)
    except Exception:
        pass

    return None


# ═══════════════════════════════════════════════
#  Intraday OHLCV Data
# ═══════════════════════════════════════════════

_TF_TO_YF = {
    "1m":  ("1d",  "1m"),
    "3m":  ("1d",  "2m"),
    "5m":  ("1d",  "5m"),
    "15m": ("5d",  "15m"),
    "1h":  ("5d",  "60m"),
    "1D":  ("1mo", "1d"),
}


def get_chart_data(yf_symbol: str, timeframe: str = "1D") -> pd.DataFrame:
    """Get OHLCV data for a specific timeframe string."""
    period, interval = _TF_TO_YF.get(timeframe, ("1d", "5m"))
    return get_intraday_data(yf_symbol, period, interval)


def get_intraday_data(symbol: str, period: str = "5d", interval: str = "5m") -> pd.DataFrame:
    """Fetch OHLCV with automatic period fallbacks."""
    for p in [period, "2d", "5d"]:
        try:
            t = yf.Ticker(symbol)
            df = t.history(period=p, interval=interval)
            if not df.empty:
                return df
        except Exception:
            pass
    return pd.DataFrame()


def get_sparkline_data(yf_symbol: str, n: int = 18) -> List[float]:
    """Last N close prices for watchlist sparkline mini-chart."""
    try:
        t = yf.Ticker(yf_symbol)
        df = t.history(period="5d", interval="30m")
        if not df.empty:
            return [round(c, 2) for c in df["Close"].tail(n).tolist()]
    except Exception:
        pass
    return []


# ═══════════════════════════════════════════════
#  Option Chain — NSE Direct
# ═══════════════════════════════════════════════

def get_option_chain_nse_direct(symbol_nse: str) -> Optional[dict]:
    """Fetch option chain from NSE India API using managed session."""
    sym = symbol_nse.strip().upper()
    if sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"):
        url = f"https://www.nseindia.com/api/option-chain-indices?symbol={sym}"
    else:
        url = f"https://www.nseindia.com/api/option-chain-equities?symbol={sym}"
    return _nse_fetch(url, timeout=14)


def compute_option_stats(records_data: list, expiry: str, spot: float) -> dict:
    """
    Compute PCR, Max Pain, total OI from NSE option chain records list.
    Returns dict with pcr, max_pain, total_ce_oi, total_pe_oi, pcr_label.
    """
    total_ce_oi = 0
    total_pe_oi = 0
    strikes_oi: dict = {}  # strike -> {ce_oi, pe_oi}

    for item in records_data:
        if item.get("expiryDate") != expiry:
            continue
        strike = item.get("strikePrice", 0)
        ce = item.get("CE", {})
        pe = item.get("PE", {})
        ce_oi = ce.get("openInterest", 0)
        pe_oi = pe.get("openInterest", 0)
        total_ce_oi += ce_oi
        total_pe_oi += pe_oi
        strikes_oi[strike] = {"ce_oi": ce_oi, "pe_oi": pe_oi}

    pcr = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 0

    # Max Pain: strike where total option payout is minimized
    max_pain_strike = 0
    min_pain = float("inf")
    for candidate in sorted(strikes_oi):
        payout = 0
        for strike, d in strikes_oi.items():
            if strike < candidate:
                payout += (candidate - strike) * d["ce_oi"]
            if strike > candidate:
                payout += (strike - candidate) * d["pe_oi"]
        if payout < min_pain:
            min_pain = payout
            max_pain_strike = candidate

    if pcr >= 1.0:
        pcr_label = "BULLISH"
    elif pcr <= 0.7:
        pcr_label = "BEARISH"
    else:
        pcr_label = "NEUTRAL"

    return {
        "pcr": pcr,
        "max_pain": max_pain_strike,
        "total_ce_oi": total_ce_oi,
        "total_pe_oi": total_pe_oi,
        "pcr_label": pcr_label,
    }


def _fmt_oi(n: int) -> str:
    """Format large OI numbers as K, L, Cr."""
    if n >= 10_000_000:
        return f"{n / 10_000_000:.2f}Cr"
    if n >= 100_000:
        return f"{n / 100_000:.2f}L"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


# ═══════════════════════════════════════════════
#  Legacy functions (kept for compatibility)
# ═══════════════════════════════════════════════

def _fetch_option_chain_inner(symbol_nse: str) -> Optional[dict]:
    data = get_option_chain_nse_direct(symbol_nse)
    if data and "records" in data:
        records = data["records"]
        total_ce_oi = 0; total_pe_oi = 0
        total_ce_oi_change = 0; total_pe_oi_change = 0
        for item in records.get("data", []):
            if "CE" in item:
                total_ce_oi += item["CE"].get("openInterest", 0)
                total_ce_oi_change += item["CE"].get("changeinOpenInterest", 0)
            if "PE" in item:
                total_pe_oi += item["PE"].get("openInterest", 0)
                total_pe_oi_change += item["PE"].get("changeinOpenInterest", 0)
        pcr = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 0
        return {
            "ce_oi": total_ce_oi, "pe_oi": total_pe_oi,
            "ce_oi_change": total_ce_oi_change, "pe_oi_change": total_pe_oi_change,
            "pcr": pcr, "net_oi_change": total_pe_oi_change - total_ce_oi_change,
        }
    return None


def get_option_chain_data(symbol_nse: str) -> Optional[dict]:
    if not symbol_nse:
        return None
    try:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(_fetch_option_chain_inner, symbol_nse)
            return future.result(timeout=15)
    except Exception:
        return None


def get_option_recommendation(symbol_nse: str, spot_price: float, action: str) -> Optional[dict]:
    try:
        data = get_option_chain_nse_direct(symbol_nse)
        if data is None or "records" not in data:
            return None
        records = data["records"]
        expiry_dates = records.get("expiryDates", [])
        nearest_expiry = expiry_dates[0] if expiry_dates else None
        all_strikes = records.get("strikePrices", [])
        atm_strike = min(all_strikes, key=lambda s: abs(s - spot_price)) if all_strikes else None
        if atm_strike is None:
            return None
        option_type = "CE" if action == "BUY" else "PE"
        step = 50 if symbol_nse in ("NIFTY", "BANKNIFTY") else 100
        strikes_to_check = [atm_strike, atm_strike + (step if option_type == "CE" else -step)]
        best_option = None
        for item in records.get("data", []):
            strike = item.get("strikePrice", 0)
            if strike not in strikes_to_check:
                continue
            if option_type not in item:
                continue
            opt = item[option_type]
            if opt.get("expiryDate") != nearest_expiry:
                continue
            entry = {
                "strike": strike, "type": option_type, "expiry": nearest_expiry,
                "ltp": opt.get("lastPrice", 0), "bid": opt.get("bidprice", 0),
                "ask": opt.get("askprice", 0), "oi": opt.get("openInterest", 0),
                "oi_change": opt.get("changeinOpenInterest", 0),
                "iv": opt.get("impliedVolatility", 0),
                "contract": f"{symbol_nse} {int(strike)} {option_type}",
            }
            if best_option is None or strike == atm_strike:
                best_option = entry
        if best_option:
            lot = {"NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 40}.get(symbol_nse, 1)
            best_option["lot_size"] = lot
            best_option["total_premium"] = round(best_option["ltp"] * lot, 2)
            best_option["premium_sl"] = round(best_option["ltp"] * 0.7, 2)
            best_option["premium_target"] = round(best_option["ltp"] * 1.5, 2)
            best_option["premium_avg"] = round(best_option["ltp"] * 0.7, 2)
        return best_option
    except Exception:
        return None


def get_current_option_ltp(symbol_nse: str, strike: float, option_type: str, expiry: str) -> Optional[float]:
    if not symbol_nse:
        return None
    try:
        data = get_option_chain_nse_direct(symbol_nse)
        if data is None or "records" not in data:
            return None
        for item in data["records"].get("data", []):
            if item.get("strikePrice") != strike:
                continue
            if option_type not in item:
                continue
            opt = item[option_type]
            if opt.get("expiryDate") != expiry:
                continue
            ltp = opt.get("lastPrice", 0)
            if ltp > 0:
                return round(float(ltp), 2)
        return None
    except Exception:
        return None


def get_prices(nifty_sym: str = "^NSEI", banknifty_sym: str = "^NSEBANK") -> dict:
    nifty = get_spot_price(nifty_sym)
    banknifty = get_spot_price(banknifty_sym)
    return {"nifty": nifty, "banknifty": banknifty}
