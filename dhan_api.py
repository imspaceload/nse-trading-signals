"""
Dhan API v2 integration module.
Provides live market quotes, option chain, and historical candle data.
Docs: https://dhanhq.co/docs/v2/
"""

import os
import csv
import io
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from functools import lru_cache

# ── Helpers to read secrets (env → st.secrets fallback) ──

def _get_secret(key: str, default: str = "") -> str:
    val = os.environ.get(key, "")
    if val:
        return val
    try:
        import streamlit as st
        return st.secrets.get(key, default)
    except Exception:
        return default


def _headers() -> dict:
    return {
        "access-token": _get_secret("DHAN_ACCESS_TOKEN"),
        "client-id": _get_secret("DHAN_CLIENT_ID", "1100225360"),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _is_configured() -> bool:
    return bool(_get_secret("DHAN_ACCESS_TOKEN"))


BASE_URL = "https://api.dhan.co/v2"

# ══════════════════════════════════════════
#  INSTRUMENT MASTER — symbol → security_id
# ══════════════════════════════════════════

_SCRIP_CACHE = {}  # {("RELIANCE", "NSE_EQ"): 11536, ...}
_SCRIP_LOADED = False


def _load_scrip_master():
    """Download and parse Dhan scrip master CSV (compact version)."""
    global _SCRIP_CACHE, _SCRIP_LOADED
    if _SCRIP_LOADED:
        return

    url = "https://images.dhan.co/api-data/api-scrip-master.csv"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        reader = csv.DictReader(io.StringIO(resp.text))
        for row in reader:
            sym = (row.get("SEM_TRADING_SYMBOL") or row.get("SM_SYMBOL_NAME") or "").strip().upper()
            seg = (row.get("SEM_SEGMENT") or "").strip()
            sec_id = row.get("SEM_SMST_SECURITY_ID") or row.get("SECURITY_ID") or ""
            exch = (row.get("SEM_EXM_EXCH_ID") or "").strip()
            inst_type = (row.get("SEM_INSTRUMENT_NAME") or "").strip()
            custom_sym = (row.get("SEM_CUSTOM_SYMBOL") or "").strip().upper()
            strike = row.get("SEM_STRIKE_PRICE", "")
            expiry = row.get("SEM_EXPIRY_DATE", "")
            opt_type = row.get("SEM_OPTION_TYPE", "")
            lot_size = row.get("SEM_LOT_UNITS", "")

            if not sec_id or not sym:
                continue

            sec_id_int = int(float(sec_id))

            # Build exchange segment key
            if exch == "NSE" and seg == "E":
                exch_seg = "NSE_EQ"
            elif exch == "NSE" and seg == "D":
                exch_seg = "NSE_FNO"
            elif exch == "BSE" and seg == "E":
                exch_seg = "BSE_EQ"
            elif exch == "BSE" and seg == "D":
                exch_seg = "BSE_FNO"
            elif exch == "MCX" and seg == "D":
                exch_seg = "MCX_COMM"
            else:
                exch_seg = f"{exch}_{seg}"

            # Store with multiple key patterns for easy lookup
            _SCRIP_CACHE[(sym, exch_seg)] = {
                "security_id": sec_id_int,
                "symbol": sym,
                "custom_symbol": custom_sym,
                "exchange_segment": exch_seg,
                "instrument_type": inst_type,
                "strike": strike,
                "expiry": expiry,
                "option_type": opt_type,
                "lot_size": lot_size,
            }
            # Also store by custom symbol
            if custom_sym and custom_sym != sym:
                _SCRIP_CACHE[(custom_sym, exch_seg)] = _SCRIP_CACHE[(sym, exch_seg)]

        _SCRIP_LOADED = True
        print(f"[Dhan] Loaded {len(_SCRIP_CACHE)} instruments from scrip master")
    except Exception as e:
        print(f"[Dhan] Failed to load scrip master: {e}")


def get_security_id(symbol: str, exchange_segment: str = "NSE_EQ") :
    """Look up Dhan security ID for a trading symbol."""
    _load_scrip_master()
    sym = symbol.strip().upper()
    entry = _SCRIP_CACHE.get((sym, exchange_segment))
    if entry:
        return entry["security_id"]
    # Try partial match
    for (s, seg), info in _SCRIP_CACHE.items():
        if seg == exchange_segment and (s == sym or info.get("custom_symbol") == sym):
            return info["security_id"]
    return None


def get_index_security_id(index_name: str) :
    """Get security ID for an index (NIFTY, BANKNIFTY, etc)."""
    _load_scrip_master()
    name = index_name.strip().upper()
    # Common index mappings
    INDEX_MAP = {
        "NIFTY": 13, "NIFTY 50": 13,
        "BANKNIFTY": 25, "BANK NIFTY": 25,
        "NIFTY BANK": 25,
        "FINNIFTY": 27,
        "SENSEX": 51,
    }
    if name in INDEX_MAP:
        return INDEX_MAP[name]
    # Try scrip master
    for (s, seg), info in _SCRIP_CACHE.items():
        if seg == "IDX_I" and (s == name or info.get("custom_symbol") == name):
            return info["security_id"]
    return None


def find_option_instruments(underlying_symbol: str, expiry: str = None,
                             strike: float = None, option_type: str = None) -> list:
    """Find option contract security IDs matching criteria."""
    _load_scrip_master()
    sym = underlying_symbol.strip().upper()
    results = []
    for (s, seg), info in _SCRIP_CACHE.items():
        if seg != "NSE_FNO":
            continue
        if info.get("instrument_type") not in ("OPTIDX", "OPTSTK"):
            continue
        # Match underlying (symbol starts with the underlying name)
        if not s.startswith(sym):
            continue
        # Filter by expiry
        if expiry and info.get("expiry") and expiry not in info["expiry"]:
            continue
        # Filter by strike
        if strike is not None and info.get("strike"):
            try:
                if abs(float(info["strike"]) - strike) > 0.01:
                    continue
            except ValueError:
                continue
        # Filter by option type
        if option_type and info.get("option_type"):
            if info["option_type"].upper() != option_type.upper():
                continue
        results.append(info)
    return results


# ══════════════════════════════════════════
#  MARKET QUOTES
# ══════════════════════════════════════════

def get_ltp(security_ids: dict) -> dict:
    """
    Get Last Traded Price for instruments.
    Args: {"NSE_EQ": [11536], "NSE_FNO": [49081]}
    Returns: {"NSE_EQ": {"11536": {"last_price": 4520}}, ...}
    """
    try:
        resp = requests.post(
            f"{BASE_URL}/marketfeed/ltp",
            headers=_headers(),
            json=security_ids,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {})
    except Exception as e:
        print(f"[Dhan] LTP fetch failed: {e}")
        return {}


def get_ohlc(security_ids: dict) -> dict:
    """
    Get OHLC data for instruments.
    Args: {"NSE_EQ": [11536]}
    Returns: {"NSE_EQ": {"11536": {"last_price": ..., "ohlc": {...}}}}
    """
    try:
        resp = requests.post(
            f"{BASE_URL}/marketfeed/ohlc",
            headers=_headers(),
            json=security_ids,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {})
    except Exception as e:
        print(f"[Dhan] OHLC fetch failed: {e}")
        return {}


def get_market_quote(security_ids: dict) -> dict:
    """
    Get full market depth + quote for instruments.
    Args: {"NSE_EQ": [11536]}
    Returns full depth, OHLC, volume, OI, circuit limits.
    """
    try:
        resp = requests.post(
            f"{BASE_URL}/marketfeed/quote",
            headers=_headers(),
            json=security_ids,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {})
    except Exception as e:
        print(f"[Dhan] Quote fetch failed: {e}")
        return {}


def get_spot_price_dhan(symbol: str, exchange_segment: str = "NSE_EQ") :
    """Get current price for a symbol using Dhan API."""
    sec_id = get_security_id(symbol, exchange_segment)
    if sec_id is None:
        return None
    data = get_ltp({exchange_segment: [sec_id]})
    if data and exchange_segment in data:
        price_data = data[exchange_segment].get(str(sec_id), {})
        return price_data.get("last_price")
    return None


# ══════════════════════════════════════════
#  HISTORICAL / CANDLE DATA
# ══════════════════════════════════════════

def get_historical_data(security_id: int, exchange_segment: str,
                        instrument: str, from_date: str, to_date: str) -> pd.DataFrame:
    """
    Get daily candle data.
    from_date, to_date: "YYYY-MM-DD"
    Returns DataFrame with Open, High, Low, Close, Volume columns.
    """
    try:
        body = {
            "securityId": str(security_id),
            "exchangeSegment": exchange_segment,
            "instrument": instrument,
            "fromDate": from_date,
            "toDate": to_date,
        }
        resp = requests.post(
            f"{BASE_URL}/charts/historical",
            headers=_headers(),
            json=body,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return _parse_candle_response(data)
    except Exception as e:
        print(f"[Dhan] Historical data failed: {e}")
        return pd.DataFrame()


def get_intraday_data_dhan(security_id: int, exchange_segment: str,
                           instrument: str, interval: str,
                           from_date: str, to_date: str) -> pd.DataFrame:
    """
    Get intraday candle data.
    interval: "1", "5", "15", "25", "60" (minutes)
    from_date, to_date: "YYYY-MM-DD HH:MM:SS" or "YYYY-MM-DD"
    Returns DataFrame with Open, High, Low, Close, Volume columns.
    """
    try:
        body = {
            "securityId": str(security_id),
            "exchangeSegment": exchange_segment,
            "instrument": instrument,
            "interval": interval,
            "fromDate": from_date,
            "toDate": to_date,
        }
        resp = requests.post(
            f"{BASE_URL}/charts/intraday",
            headers=_headers(),
            json=body,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return _parse_candle_response(data)
    except Exception as e:
        print(f"[Dhan] Intraday data failed: {e}")
        return pd.DataFrame()


def _parse_candle_response(data: dict) -> pd.DataFrame:
    """Parse Dhan candle API response into a pandas DataFrame."""
    if not data:
        return pd.DataFrame()

    opens = data.get("open", [])
    highs = data.get("high", [])
    lows = data.get("low", [])
    closes = data.get("close", [])
    volumes = data.get("volume", [])
    timestamps = data.get("timestamp", data.get("start_Time", []))

    if not opens or not timestamps:
        return pd.DataFrame()

    df = pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": volumes if volumes else [0] * len(opens),
    })

    # Parse timestamps
    try:
        df.index = pd.to_datetime(timestamps, unit='s')
    except Exception:
        try:
            df.index = pd.to_datetime(timestamps)
        except Exception:
            df.index = range(len(df))

    df.index.name = "Datetime"
    return df


def get_candles_for_symbol(symbol: str, period: str = "5d",
                           interval: str = "5", exchange_segment: str = "NSE_EQ") -> pd.DataFrame:
    """
    High-level helper: get candle data for a symbol name.
    period: "1d", "5d", "1mo"
    interval: "1", "5", "15", "25", "60" (minutes)
    """
    sec_id = get_security_id(symbol, exchange_segment)
    if sec_id is None:
        print(f"[Dhan] Security ID not found for {symbol} on {exchange_segment}")
        return pd.DataFrame()

    # Determine instrument type
    if exchange_segment == "NSE_EQ":
        instrument = "EQUITY"
    elif exchange_segment == "BSE_EQ":
        instrument = "EQUITY"
    elif exchange_segment == "IDX_I":
        instrument = "INDEX"
    elif exchange_segment == "MCX_COMM":
        instrument = "FUTCOM"
    else:
        instrument = "EQUITY"

    # Calculate date range
    now = datetime.now()
    if period == "1d":
        from_dt = now.strftime("%Y-%m-%d 09:00:00")
        to_dt = now.strftime("%Y-%m-%d %H:%M:%S")
    elif period == "5d":
        from_dt = (now - timedelta(days=7)).strftime("%Y-%m-%d 09:00:00")
        to_dt = now.strftime("%Y-%m-%d %H:%M:%S")
    elif period == "1mo":
        from_dt = (now - timedelta(days=30)).strftime("%Y-%m-%d 09:00:00")
        to_dt = now.strftime("%Y-%m-%d %H:%M:%S")
    else:
        from_dt = (now - timedelta(days=7)).strftime("%Y-%m-%d 09:00:00")
        to_dt = now.strftime("%Y-%m-%d %H:%M:%S")

    # Use daily endpoint for longer periods, intraday for shorter
    if period == "1mo" and interval in ("25", "60"):
        return get_intraday_data_dhan(sec_id, exchange_segment, instrument, interval, from_dt, to_dt)
    else:
        return get_intraday_data_dhan(sec_id, exchange_segment, instrument, interval, from_dt, to_dt)


# ══════════════════════════════════════════
#  OPTION CHAIN
# ══════════════════════════════════════════

def _seg_to_type(segment: str) -> str:
    """Map Dhan exchange segment to UnderlyingType for option chain API."""
    if "IDX" in segment:
        return "IDX"
    return "EQUITY"


def get_expiry_list(underlying_security_id: int, underlying_segment: str = "IDX_I") -> list:
    """Get list of active expiry dates for an underlying."""
    try:
        body = {
            "UnderlyingScrip": underlying_security_id,
            "UnderlyingType": _seg_to_type(underlying_segment),
        }
        resp = requests.post(
            f"{BASE_URL}/optionchain/expirylist",
            headers=_headers(),
            json=body,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else data.get("data", [])
    except Exception as e:
        print(f"[Dhan] Expiry list failed: {e}")
        return []


def get_option_chain_dhan(underlying_security_id: int,
                          underlying_segment: str = "IDX_I",
                          expiry: str = None) -> dict:
    """
    Get option chain data from Dhan.
    Returns: {"last_price": ..., "oc": {strike: {"CE": {...}, "PE": {...}}}}
    """
    try:
        body = {
            "UnderlyingScrip": underlying_security_id,
            "UnderlyingType": _seg_to_type(underlying_segment),
        }
        if expiry:
            body["ExpiryDate"] = expiry

        resp = requests.post(
            f"{BASE_URL}/optionchain",
            headers=_headers(),
            json=body,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[Dhan] Option chain failed: {e}")
        return {}


def get_option_chain_for_symbol(symbol: str, expiry: str = None) -> dict:
    """
    High-level helper: get option chain for a symbol name.
    Works for both indices (NIFTY, BANKNIFTY) and stocks (RELIANCE, IDEA).
    Returns parsed option chain data compatible with app.py format.
    """
    sym = symbol.strip().upper()

    if not _is_configured():
        print(f"[Dhan] Not configured — DHAN_ACCESS_TOKEN missing")
        return None

    # Determine underlying security ID and segment
    idx_id = get_index_security_id(sym)
    if idx_id is not None:
        sec_id = idx_id
        seg = "IDX_I"
    else:
        sec_id = get_security_id(sym, "NSE_EQ")
        seg = "NSE_EQ"

    if sec_id is None:
        print(f"[Dhan] Security ID not found for {sym}")
        return None

    print(f"[Dhan] OC lookup: sym={sym} sec_id={sec_id} seg={seg} type={_seg_to_type(seg)}")

    # Get expiry list if not provided
    if not expiry:
        expiries = get_expiry_list(sec_id, seg)
        print(f"[Dhan] Expiries for {sym}: {expiries[:3] if expiries else 'NONE'}")
        if expiries:
            expiry = expiries[0]  # nearest expiry
        else:
            return None

    # Fetch option chain
    oc_data = get_option_chain_dhan(sec_id, seg, expiry)
    if not oc_data:
        print(f"[Dhan] Empty OC response for {sym} expiry={expiry}")
        return None

    oc_keys = list(oc_data.get("oc", {}).keys())[:3] if "oc" in oc_data else list(oc_data.keys())[:5]
    print(f"[Dhan] OC response keys: {oc_keys} last_price={oc_data.get('last_price')}")

    return {
        "raw": oc_data,
        "underlying_price": oc_data.get("last_price", 0),
        "expiry": expiry,
        "expiry_list": get_expiry_list(sec_id, seg),
    }


# ══════════════════════════════════════════
#  SYMBOL MAPPING HELPERS
# ══════════════════════════════════════════

# Map config.py symbol names to Dhan exchange segments
SYMBOL_SEGMENT_MAP = {
    "NIFTY 50": ("IDX_I", "INDEX"),
    "BANK NIFTY": ("IDX_I", "INDEX"),
    "SENSEX": ("IDX_I", "INDEX"),
    "MCX CRUDE OIL": ("MCX_COMM", "FUTCOM"),
    "MCX NATURAL GAS": ("MCX_COMM", "FUTCOM"),
    "MCX GOLD": ("MCX_COMM", "FUTCOM"),
    "MCX SILVER": ("MCX_COMM", "FUTCOM"),
}


def resolve_symbol(symbol_name: str, sym_config: dict) -> tuple:
    """
    Resolve a symbol name + config dict to (security_id, exchange_segment, instrument).
    Returns (None, None, None) if not found.
    """
    name = symbol_name.strip().upper()
    nse_sym = sym_config.get("nse", "")

    # Check special mappings first
    if name in SYMBOL_SEGMENT_MAP:
        seg, inst = SYMBOL_SEGMENT_MAP[name]
        if seg == "IDX_I":
            sec_id = get_index_security_id(name)
        else:
            sec_id = get_security_id(nse_sym or name, seg)
        return (sec_id, seg, inst)

    # Default: NSE equity
    if nse_sym:
        sec_id = get_security_id(nse_sym, "NSE_EQ")
        if sec_id:
            return (sec_id, "NSE_EQ", "EQUITY")

    # Try the symbol name directly
    sec_id = get_security_id(name, "NSE_EQ")
    if sec_id:
        return (sec_id, "NSE_EQ", "EQUITY")

    return (None, None, None)


# ══════════════════════════════════════════
#  NSE FORMAT CONVERTER
# ══════════════════════════════════════════

def _convert_dhan_oc_to_nse(oc_result: dict) -> dict:
    """Convert Dhan option chain result to NSE-compatible format for app rendering."""
    if not oc_result:
        return {}

    raw = oc_result.get("raw", oc_result)
    underlying_price = float(oc_result.get("underlying_price", 0) or 0)
    expiry = oc_result.get("expiry", "")
    expiry_list = oc_result.get("expiry_list", [])

    # Navigate into "data" wrapper if present
    data_sec = raw.get("data", raw) if isinstance(raw, dict) else raw

    # Locate the oc dict (keyed by strike price string)
    oc_dict = (
        data_sec.get("oc") or data_sec.get("OC") or
        raw.get("oc") or {}
    ) if isinstance(data_sec, dict) else {}

    if not oc_dict:
        return {}

    spot = (
        underlying_price or
        (data_sec.get("last_price") if isinstance(data_sec, dict) else 0) or
        (data_sec.get("lastTradedPrice") if isinstance(data_sec, dict) else 0) or
        (raw.get("last_price") if isinstance(raw, dict) else 0) or 0
    )

    def _fmt_exp(e):
        if not e:
            return e
        try:
            from datetime import datetime as _dt
            return _dt.strptime(str(e), "%Y-%m-%d").strftime("%d-%b-%Y").upper()
        except Exception:
            return str(e)

    exp_fmt = _fmt_exp(expiry)
    expiry_list_fmt = [_fmt_exp(e) for e in expiry_list] if expiry_list else ([exp_fmt] if exp_fmt else [])

    def _pick(*keys, d):
        for k in keys:
            v = d.get(k)
            if v is not None:
                try:
                    return float(v)
                except Exception:
                    pass
        return 0.0

    records = []
    for strike_key, sd in oc_dict.items():
        try:
            strike = float(strike_key)
        except (ValueError, TypeError):
            continue

        ce = {
            "openInterest":         int(_pick("call_oi",  "callOI",   "ce_oi",  d=sd)),
            "changeinOpenInterest": int(_pick("call_oiChange", "callOIChange", d=sd)),
            "totalTradedVolume":    int(_pick("call_vol", "call_volume", "callVol", d=sd)),
            "impliedVolatility":    _pick("call_iv", "callIV", d=sd),
            "lastPrice":            _pick("call_ltp", "callLTP", d=sd),
            "bidprice":             _pick("call_bid", "callBid", "topCallBid", d=sd),
            "askprice":             _pick("call_ask", "callAsk", "topCallAsk", d=sd),
            "expiryDate": exp_fmt, "strikePrice": strike,
        }
        pe = {
            "openInterest":         int(_pick("put_oi",  "putOI",  "pe_oi",  d=sd)),
            "changeinOpenInterest": int(_pick("put_oiChange", "putOIChange", d=sd)),
            "totalTradedVolume":    int(_pick("put_vol", "put_volume", "putVol", d=sd)),
            "impliedVolatility":    _pick("put_iv", "putIV", d=sd),
            "lastPrice":            _pick("put_ltp", "putLTP", d=sd),
            "bidprice":             _pick("put_bid", "putBid", "topPutBid", d=sd),
            "askprice":             _pick("put_ask", "putAsk", "topPutAsk", d=sd),
            "expiryDate": exp_fmt, "strikePrice": strike,
        }
        records.append({"strikePrice": strike, "expiryDate": exp_fmt, "CE": ce, "PE": pe})

    if not records:
        return {}

    records.sort(key=lambda r: r["strikePrice"])
    return {
        "records": {
            "expiryDates": expiry_list_fmt,
            "data": records,
            "underlyingValue": float(spot),
            "strikePrices": [r["strikePrice"] for r in records],
        },
        "_source": "dhan",
    }
