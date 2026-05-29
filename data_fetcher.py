"""
Lean data fetcher. Dhan primary (any IP), NSE direct fallback (Indian IP), yfinance last resort.
No NSE session management — simple requests with headers work fine from Indian IPs.
"""
from typing import Optional, List
import concurrent.futures
import requests
import pandas as pd
from datetime import datetime, timedelta
import pytz

from config import (
    MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE,
    MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE,
)

IST = pytz.timezone("Asia/Kolkata")

_NSE_HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/",
    "X-Requested-With": "XMLHttpRequest",
}

_nse_session: Optional[requests.Session] = None

def _get_nse_session() -> requests.Session:
    global _nse_session
    if _nse_session is None:
        s = requests.Session()
        s.headers.update(_NSE_HDRS)
        try:
            s.get("https://www.nseindia.com", timeout=8)
        except Exception:
            pass
        _nse_session = s
    return _nse_session

def _nse(url: str, timeout: int = 10) -> Optional[dict]:
    try:
        s = _get_nse_session()
        r = s.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        global _nse_session
        _nse_session = None
        return None


# ── Market Status ─────────────────────────────────────────────────

def is_market_open() -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    mo = now.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0)
    mc = now.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0, microsecond=0)
    return mo <= now <= mc


def get_market_opens_in() -> str:
    now = datetime.now(IST)
    for d in range(7):
        c = now + timedelta(days=d)
        if c.weekday() < 5:
            op = c.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0)
            if op > now:
                s = int((op - now).total_seconds())
                return f"{s // 3600}h {(s % 3600) // 60}m"
    return "--"


# ── NSE Indices ───────────────────────────────────────────────────

_IDX_ALIAS = {
    "NIFTY 50": "NIFTY 50",
    "NIFTY BANK": "BANK NIFTY",
    "NIFTY FIN SERVICE": "FIN NIFTY",
    "Nifty Financial Services": "FIN NIFTY",
    "NIFTY FINANCIAL SERVICES": "FIN NIFTY",
    "NIFTY MIDCAP SELECT": "MIDCAP SELECT",
    "NIFTY MIDCAP 50": "MIDCAP SELECT",
    "INDIA VIX": "INDIA VIX",
}


def get_nse_indices() -> dict:
    data = _nse("https://www.nseindia.com/api/allIndices", timeout=8)
    if not data:
        return {}
    out = {}
    for item in data.get("data", []):
        raw = item.get("index", "")
        key = _IDX_ALIAS.get(raw, raw)
        d = {
            "price":  item.get("last", 0),
            "change": round(item.get("variation", 0), 2),
            "pct":    round(item.get("percentChange", 0), 2),
            "open":   item.get("open", 0),
            "high":   item.get("dayHigh", item.get("high", 0)),
            "low":    item.get("dayLow",  item.get("low",  0)),
        }
        out[key] = d
        if raw != key:
            out[raw] = d
    return out


def get_global_cues() -> dict:
    return {"sgx_nifty": None, "dow_futures": None, "brent": None, "usdinr": None}


# ── Spot Price ────────────────────────────────────────────────────

_IDX_LOOKUP = {
    "NIFTY": "NIFTY 50", "BANKNIFTY": "BANK NIFTY",
    "FINNIFTY": "FIN NIFTY", "MIDCPNIFTY": "MIDCAP SELECT",
}
_IDX_DHAN_IDS = {"NIFTY": 13, "BANKNIFTY": 25, "FINNIFTY": 27, "MIDCPNIFTY": 27}


def get_spot_price(symbol: str, nse_symbol: str = None) -> Optional[float]:
    nse_up = (nse_symbol or "").strip().upper()

    # 1. Dhan LTP — works from any IP
    try:
        from dhan_api import _is_configured, get_ltp, get_security_id
        if _is_configured() and nse_up:
            if nse_up in _IDX_DHAN_IDS:
                sid = _IDX_DHAN_IDS[nse_up]
                d = get_ltp({"IDX_I": [sid]})
                p = (d or {}).get("IDX_I", {}).get(str(sid), {}).get("last_price")
                if p and float(p) > 0:
                    return round(float(p), 2)
            else:
                sid = get_security_id(nse_up, "NSE_EQ")
                if sid:
                    d = get_ltp({"NSE_EQ": [sid]})
                    p = (d or {}).get("NSE_EQ", {}).get(str(sid), {}).get("last_price")
                    if p and float(p) > 0:
                        return round(float(p), 2)
    except Exception:
        pass

    # 2. NSE API — works from Indian IP
    if nse_up:
        if nse_up in _IDX_LOOKUP:
            data = _nse("https://www.nseindia.com/api/allIndices", timeout=6)
            if data:
                target = _IDX_LOOKUP[nse_up]
                for item in data.get("data", []):
                    alias = _IDX_ALIAS.get(item.get("index", ""), item.get("index", ""))
                    if alias == target:
                        p = item.get("last")
                        if p and float(p) > 0:
                            return round(float(p), 2)
        else:
            data = _nse(f"https://www.nseindia.com/api/quote-equity?symbol={nse_up}", timeout=6)
            if data:
                p = data.get("priceInfo", {}).get("lastPrice")
                if p and float(p) > 0:
                    return round(float(p), 2)

    # 3. yfinance — works from Indian IP, last resort
    try:
        import yfinance as yf
        fi = yf.Ticker(symbol).fast_info
        p = fi.get("lastPrice") or fi.get("regularMarketPrice")
        if p and float(p) > 0:
            return round(float(p), 2)
    except Exception:
        pass

    return None


# ── OHLCV (for signal computation — chart uses TradingView widget) ─

_TF_YF = {
    "1m":  ("1d",  "1m"),
    "3m":  ("1d",  "2m"),
    "5m":  ("1d",  "5m"),
    "15m": ("5d",  "15m"),
    "1h":  ("5d",  "60m"),
    "1D":  ("1mo", "1d"),
}
_TF_DHAN_INT = {
    "1m": "1", "3m": "1", "5m": "5", "15m": "15", "1h": "60", "1D": "60",
}
_YF_INT_DHAN = {
    "1m": "1", "2m": "1", "5m": "5", "15m": "15", "30m": "25", "60m": "60", "1d": "60",
}
_IDX_YF_NSE = {
    "^NSEI": "NIFTY 50", "^NSEBANK": "BANK NIFTY",
    "^CNXFIN": "FIN NIFTY", "^BSESN": "SENSEX",
}
_IDX_SEGS = {"NIFTY 50", "BANK NIFTY", "FIN NIFTY", "MIDCAP SELECT", "SENSEX"}


def get_intraday_data(symbol: str, period: str = "5d", interval: str = "5m") -> pd.DataFrame:
    dhan_int = _YF_INT_DHAN.get(interval, "5")
    nse_sym = _IDX_YF_NSE.get(symbol, symbol.replace(".NS", ""))
    seg = "IDX_I" if nse_sym in _IDX_SEGS else "NSE_EQ"

    # 1. Dhan
    try:
        from dhan_api import get_candles_for_symbol, _is_configured
        if _is_configured():
            df = get_candles_for_symbol(nse_sym, period=period, interval=dhan_int, exchange_segment=seg)
            if not df.empty:
                return df
    except Exception:
        pass

    # 2. yfinance (works from Indian IP)
    try:
        import yfinance as yf
        for p in [period, "2d", "5d"]:
            try:
                df = yf.Ticker(symbol).history(period=p, interval=interval)
                if not df.empty:
                    return df
            except Exception:
                pass
    except Exception:
        pass

    return pd.DataFrame()


def get_chart_data(yf_symbol: str, timeframe: str = "1D") -> pd.DataFrame:
    period, interval = _TF_YF.get(timeframe, ("1d", "5m"))
    return get_intraday_data(yf_symbol, period, interval)


def get_sparkline_data(yf_symbol: str, n: int = 18) -> List[float]:
    nse_sym = _IDX_YF_NSE.get(yf_symbol, yf_symbol.replace(".NS", ""))
    seg = "IDX_I" if nse_sym in _IDX_SEGS else "NSE_EQ"
    try:
        from dhan_api import get_candles_for_symbol, _is_configured
        if _is_configured():
            df = get_candles_for_symbol(nse_sym, period="5d", interval="60", exchange_segment=seg)
            if not df.empty:
                return [round(c, 2) for c in df["Close"].tail(n).tolist()]
    except Exception:
        pass
    try:
        import yfinance as yf
        df = yf.Ticker(yf_symbol).history(period="5d", interval="30m")
        if not df.empty:
            return [round(c, 2) for c in df["Close"].tail(n).tolist()]
    except Exception:
        pass
    return []


# ── Option Chain ──────────────────────────────────────────────────

def get_option_chain_nse_direct(symbol_nse: str) -> Optional[dict]:
    sym = symbol_nse.strip().upper()

    # 1. Dhan — dedicated endpoint, works from any IP
    try:
        from dhan_api import get_option_chain_for_symbol, _is_configured, _convert_dhan_oc_to_nse
        if _is_configured():
            raw = get_option_chain_for_symbol(sym)
            if raw:
                nse_fmt = _convert_dhan_oc_to_nse(raw)
                if nse_fmt and "records" in nse_fmt:
                    return nse_fmt
    except Exception:
        pass

    # 2. NSE direct — works from Indian IP
    if sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"):
        url = f"https://www.nseindia.com/api/option-chain-indices?symbol={sym}"
    else:
        url = f"https://www.nseindia.com/api/option-chain-equities?symbol={sym}"
    print(f"[NSE] Fetching OC: {url}")
    data = _nse(url, timeout=10)
    if data and "records" in data:
        print(f"[NSE] OC OK for {sym} — {len(data['records'].get('data',[]))} rows")
        return data
    print(f"[NSE] OC failed for {sym} — response keys: {list(data.keys()) if isinstance(data, dict) else data}")
    return None


def compute_option_stats(records_data: list, expiry: str, spot: float) -> dict:
    total_ce = total_pe = 0
    strikes: dict = {}
    for item in records_data:
        if item.get("expiryDate") != expiry:
            continue
        s = item.get("strikePrice", 0)
        ce_oi = item.get("CE", {}).get("openInterest", 0)
        pe_oi = item.get("PE", {}).get("openInterest", 0)
        total_ce += ce_oi
        total_pe += pe_oi
        strikes[s] = {"ce_oi": ce_oi, "pe_oi": pe_oi}

    pcr = round(total_pe / total_ce, 2) if total_ce > 0 else 0

    max_pain = 0
    min_pain = float("inf")
    for c in sorted(strikes):
        pain = sum(
            (c - s) * d["ce_oi"] if s < c else (s - c) * d["pe_oi"] if s > c else 0
            for s, d in strikes.items()
        )
        if pain < min_pain:
            min_pain = pain
            max_pain = c

    pcr_label = "BULLISH" if pcr >= 1.0 else ("BEARISH" if pcr <= 0.7 else "NEUTRAL")
    return {
        "pcr": pcr, "max_pain": max_pain,
        "total_ce_oi": total_ce, "total_pe_oi": total_pe, "pcr_label": pcr_label,
    }


def _fmt_oi(n: int) -> str:
    if n >= 10_000_000: return f"{n / 10_000_000:.2f}Cr"
    if n >= 100_000:    return f"{n / 100_000:.2f}L"
    if n >= 1_000:      return f"{n / 1_000:.1f}K"
    return str(n)


# ── NSE quote helper ──────────────────────────────────────────────

def get_nse_quote(symbol_nse: str) -> Optional[dict]:
    return _nse(f"https://www.nseindia.com/api/quote-equity?symbol={symbol_nse.upper()}", timeout=8)


# ── Compatibility functions (used by app.py) ──────────────────────

def _fetch_option_chain_inner(symbol_nse: str) -> Optional[dict]:
    data = get_option_chain_nse_direct(symbol_nse)
    if not data or "records" not in data:
        return None
    ce = pe = ce_c = pe_c = 0
    for item in data["records"].get("data", []):
        if "CE" in item:
            ce += item["CE"].get("openInterest", 0)
            ce_c += item["CE"].get("changeinOpenInterest", 0)
        if "PE" in item:
            pe += item["PE"].get("openInterest", 0)
            pe_c += item["PE"].get("changeinOpenInterest", 0)
    pcr = round(pe / ce, 2) if ce > 0 else 0
    return {"ce_oi": ce, "pe_oi": pe, "ce_oi_change": ce_c, "pe_oi_change": pe_c,
            "pcr": pcr, "net_oi_change": pe_c - ce_c}


def get_option_chain_data(symbol_nse: str) -> Optional[dict]:
    if not symbol_nse:
        return None
    try:
        return _fetch_option_chain_inner(symbol_nse)
    except Exception:
        return None


def get_option_recommendation(symbol_nse: str, spot_price: float, action: str) -> Optional[dict]:
    try:
        data = get_option_chain_nse_direct(symbol_nse)
        if not data or "records" not in data:
            return None
        records = data["records"]
        expiry_dates = records.get("expiryDates", [])
        nearest = expiry_dates[0] if expiry_dates else None
        all_s = sorted(set(i.get("strikePrice", 0) for i in records.get("data", [])))
        atm = min(all_s, key=lambda s: abs(s - spot_price)) if all_s else None
        if not atm:
            return None
        ot = "CE" if action == "BUY" else "PE"
        step = 50 if symbol_nse in ("NIFTY", "BANKNIFTY") else 100
        checks = {atm, atm + (step if ot == "CE" else -step)}
        best = None
        for item in records.get("data", []):
            strike = item.get("strikePrice", 0)
            if strike not in checks or ot not in item:
                continue
            opt = item[ot]
            if opt.get("expiryDate") != nearest:
                continue
            e = {
                "strike": strike, "type": ot, "expiry": nearest,
                "ltp": opt.get("lastPrice", 0), "bid": opt.get("bidprice", 0),
                "ask": opt.get("askprice", 0), "oi": opt.get("openInterest", 0),
                "oi_change": opt.get("changeinOpenInterest", 0),
                "iv": opt.get("impliedVolatility", 0),
                "contract": f"{symbol_nse} {int(strike)} {ot}",
            }
            if best is None or strike == atm:
                best = e
        if best:
            lot = {"NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 40}.get(symbol_nse, 1)
            best.update({
                "lot_size": lot,
                "total_premium": round(best["ltp"] * lot, 2),
                "premium_sl": round(best["ltp"] * 0.7, 2),
                "premium_target": round(best["ltp"] * 1.5, 2),
                "premium_avg": round(best["ltp"] * 0.7, 2),
            })
        return best
    except Exception:
        return None


def get_current_option_ltp(symbol_nse: str, strike: float, option_type: str, expiry: str) -> Optional[float]:
    if not symbol_nse:
        return None
    try:
        data = get_option_chain_nse_direct(symbol_nse)
        if not data or "records" not in data:
            return None
        for item in data["records"].get("data", []):
            if item.get("strikePrice") != strike or option_type not in item:
                continue
            opt = item[option_type]
            if opt.get("expiryDate") == expiry:
                ltp = opt.get("lastPrice", 0)
                if ltp > 0:
                    return round(float(ltp), 2)
    except Exception:
        pass
    return None


def get_prices(nifty_sym: str = "^NSEI", banknifty_sym: str = "^NSEBANK") -> dict:
    return {
        "nifty": get_spot_price(nifty_sym, "NIFTY"),
        "banknifty": get_spot_price(banknifty_sym, "BANKNIFTY"),
    }
