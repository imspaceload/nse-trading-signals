"""
Zerodha Kite Connect integration.
Handles OAuth login, real-time data, historical candles, and order placement for algo trading.
"""
import os
import io
import csv
import time
import json
import threading
import concurrent.futures
import requests as _requests
from typing import Optional, List, Dict
from datetime import datetime, timedelta
import pandas as pd
import pytz

IST = pytz.timezone("Asia/Kolkata")

# ── Secrets ────────────────────────────────────────────────────────────────

def _get_secret(key: str, default: str = "") -> str:
    val = os.environ.get(key, "")
    if val:
        return val
    try:
        import streamlit as st
        return st.secrets.get(key, default)
    except Exception:
        return default


def _kite_api_key() -> str:
    return os.environ.get("KITE_API_KEY") or _get_secret("KITE_API_KEY")

def _kite_api_secret() -> str:
    return os.environ.get("KITE_API_SECRET") or _get_secret("KITE_API_SECRET")

def _kite_access_token() -> str:
    """Return the current live access token from the active kite instance."""
    global _kite
    if _kite is not None:
        try:
            return _kite.access_token or ""
        except Exception:
            pass
    return os.environ.get("KITE_ACCESS_TOKEN") or _get_secret("KITE_ACCESS_TOKEN")

# Keep module-level refs for backward compat (refreshed via functions above)
KITE_API_KEY    = _kite_api_key()
KITE_API_SECRET = _kite_api_secret()

# ── Token Persistence ──────────────────────────────────────────────────────

_TOKEN_FILE = "kite_token.json"


def _save_token(access_token: str, login_date: str):
    try:
        from sms_sender import _get_supabase
        sb = _get_supabase()
        if sb:
            try:
                sb.table("config").upsert({
                    "key": "kite_access_token",
                    "value": access_token,
                    "updated_at": datetime.now(IST).isoformat(),
                }).execute()
                sb.table("config").upsert({
                    "key": "kite_login_date",
                    "value": login_date,
                    "updated_at": datetime.now(IST).isoformat(),
                }).execute()
                return
            except Exception:
                pass
    except Exception:
        pass
    # Fallback: local JSON
    with open(_TOKEN_FILE, "w") as f:
        json.dump({"access_token": access_token, "login_date": login_date}, f)


def _load_saved_token() -> tuple:
    """Returns (access_token, login_date) or (None, None)."""
    try:
        from sms_sender import _get_supabase
        sb = _get_supabase()
        if sb:
            try:
                rows = sb.table("config").select("key,value").in_(
                    "key", ["kite_access_token", "kite_login_date"]
                ).execute()
                d = {r["key"]: r["value"] for r in (rows.data or [])}
                if d.get("kite_access_token"):
                    return d["kite_access_token"], d.get("kite_login_date", "")
            except Exception:
                pass
    except Exception:
        pass
    # Fallback: local JSON
    try:
        with open(_TOKEN_FILE) as f:
            data = json.load(f)
            return data.get("access_token"), data.get("login_date", "")
    except Exception:
        pass
    return None, None


# ── KiteConnect Singleton ──────────────────────────────────────────────────

_kite = None
_kite_lock = threading.Lock()
_kite_connected = False

# Stable instrument tokens for major NSE indices (rarely change)
_INDEX_TOKENS: Dict[str, int] = {
    "NIFTY 50":       256265,
    "BANK NIFTY":     260105,
    "FIN NIFTY":      257801,
    "MIDCAP SELECT":  288009,
    "INDIA VIX":      264969,
}

# Kite interval strings
_TF_TO_KITE = {
    "1m":  "minute",
    "3m":  "3minute",
    "5m":  "5minute",
    "15m": "15minute",
    "30m": "30minute",
    "1h":  "60minute",
    "1D":  "day",
}

# How many days back to fetch per timeframe
_TF_DAYS_BACK = {
    "1m":  1,
    "3m":  1,
    "5m":  2,
    "15m": 5,
    "30m": 10,
    "1h":  30,
    "1D":  365,
}

# NSE symbol → instrument token cache
_equity_token_cache: Dict[str, int] = {}
_instruments_df: Optional[pd.DataFrame] = None
_instruments_loaded_at: float = 0


def get_kite():
    """Return the KiteConnect instance (lazy init). Re-reads API key each call."""
    global _kite
    api_key = _kite_api_key()
    if not api_key:
        return None
    if _kite is not None:
        return _kite
    with _kite_lock:
        if _kite is None:
            try:
                from kiteconnect import KiteConnect
                _kite = KiteConnect(api_key=_kite_api_key())
            except Exception:
                return None
    return _kite


def is_configured() -> bool:
    """True if API key + secret are present in environment variables."""
    return bool(
        os.environ.get("KITE_API_KEY", "").strip() and
        os.environ.get("KITE_API_SECRET", "").strip()
    )


# Cache connected state for 60s to avoid profile() call on every render
_connected_cache: bool = False
_connected_checked_at: float = 0
_CONNECTED_TTL = 60


def is_connected() -> bool:
    """True if access token is valid. Cached 60s to avoid per-render network call."""
    global _connected_cache, _connected_checked_at, _kite_connected
    now = time.time()
    if now - _connected_checked_at < _CONNECTED_TTL:
        return _connected_cache
    kite = get_kite()
    if not kite:
        return False
    try:
        kite.profile()
        _connected_cache = True
        _kite_connected = True
    except Exception:
        _connected_cache = False
        _kite_connected = False
    _connected_checked_at = now
    return _connected_cache


def restore_saved_token() -> bool:
    """Try to restore today's saved token. Returns True if successful."""
    today = datetime.now(IST).strftime("%Y-%m-%d")
    token, login_date = _load_saved_token()
    if token and login_date == today:
        kite = get_kite()
        if kite:
            kite.set_access_token(token)
            # Quick validate
            try:
                kite.profile()
                global _kite_connected
                _kite_connected = True
                return True
            except Exception:
                pass
    return False


def get_login_url() -> str:
    """Return Zerodha OAuth login URL."""
    kite = get_kite()
    return kite.login_url() if kite else ""


def complete_login(request_token: str) -> Optional[str]:
    """
    Exchange request_token for access_token.
    Called once per day after user logs in via Zerodha.
    Returns access_token string or None on failure.
    """
    kite = get_kite()
    if not kite or not KITE_API_SECRET or not request_token:
        return None
    try:
        data = kite.generate_session(request_token, api_secret=KITE_API_SECRET)
        access_token = data["access_token"]
        kite.set_access_token(access_token)
        today = datetime.now(IST).strftime("%Y-%m-%d")
        _save_token(access_token, today)
        global _kite_connected, _connected_cache, _connected_checked_at
        _kite_connected = True
        _connected_cache = True
        _connected_checked_at = time.time()
        return access_token
    except Exception as e:
        return None


# ── Instruments ────────────────────────────────────────────────────────────

def _load_instruments(exchange: str = "NSE") -> Optional[pd.DataFrame]:
    """Load instruments CSV from Kite (cached for 24h)."""
    global _instruments_df, _instruments_loaded_at
    now = time.time()
    if _instruments_df is not None and (now - _instruments_loaded_at) < 86400:
        return _instruments_df
    kite = get_kite()
    if not kite:
        return None
    try:
        rows = kite.instruments(exchange)
        _instruments_df = pd.DataFrame(rows)
        _instruments_loaded_at = now
        return _instruments_df
    except Exception:
        return None


def get_instrument_token(tradingsymbol: str, exchange: str = "NSE") -> Optional[int]:
    """Look up instrument token by symbol."""
    # Check index map first
    key_map = {
        "NIFTY":      "NIFTY 50",
        "BANKNIFTY":  "BANK NIFTY",
        "FINNIFTY":   "FIN NIFTY",
        "MIDCPNIFTY": "MIDCAP SELECT",
    }
    mapped = key_map.get(tradingsymbol.upper(), tradingsymbol)
    if mapped in _INDEX_TOKENS:
        return _INDEX_TOKENS[mapped]

    # Equity cache
    cache_key = f"{exchange}:{tradingsymbol}"
    if cache_key in _equity_token_cache:
        return _equity_token_cache[cache_key]

    df = _load_instruments(exchange)
    if df is None or df.empty:
        return None
    match = df[
        (df["tradingsymbol"] == tradingsymbol.upper()) &
        (df["exchange"] == exchange)
    ]
    if not match.empty:
        token = int(match.iloc[0]["instrument_token"])
        _equity_token_cache[cache_key] = token
        return token
    return None


def get_nfo_instrument_token(symbol: str, strike: float, opt_type: str, expiry_str: str) -> Optional[int]:
    """
    Find NFO instrument token for an option contract.
    expiry_str: 'DD-Mon-YYYY' format from NSE option chain
    """
    kite = get_kite()
    if not kite:
        return None
    try:
        rows = kite.instruments("NFO")
        df = pd.DataFrame(rows)
        # Parse expiry
        exp = pd.to_datetime(expiry_str, dayfirst=True, errors="coerce")
        if pd.isna(exp):
            return None
        mask = (
            (df["name"] == symbol.upper()) &
            (df["strike"] == float(strike)) &
            (df["instrument_type"] == opt_type.upper()) &
            (df["expiry"] == exp.date())
        )
        match = df[mask]
        if not match.empty:
            return int(match.iloc[0]["instrument_token"])
    except Exception:
        pass
    return None


# ── Live Data ──────────────────────────────────────────────────────────────

def get_ltp(symbol: str, exchange: str = "NSE") -> Optional[float]:
    """Get last traded price for a symbol."""
    kite = get_kite()
    if not kite:
        return None
    # Map index names
    sym_map = {
        "NIFTY 50":    "NIFTY 50",
        "BANK NIFTY":  "NIFTY BANK",
        "FIN NIFTY":   "NIFTY FIN SERVICE",
        "MIDCAP SELECT": "NIFTY MIDCAP SELECT",
    }
    kite_sym = sym_map.get(symbol, symbol)
    key = f"{exchange}:{kite_sym}"
    try:
        data = kite.ltp([key])
        if key in data:
            return round(float(data[key]["last_price"]), 2)
    except Exception:
        pass
    return None


def get_quotes(symbols: List[str], exchange: str = "NSE") -> dict:
    """
    Get full quote (OHLC + LTP) for multiple symbols.
    Returns {symbol: {"last_price", "open", "high", "low", "close", "volume", "change", "pct"}}
    """
    kite = get_kite()
    if not kite:
        return {}
    keys = [f"{exchange}:{s}" for s in symbols]
    try:
        raw = kite.quote(keys)
        result = {}
        for k, v in raw.items():
            sym = k.split(":", 1)[-1]
            ohlc = v.get("ohlc", {})
            ltp = v.get("last_price", 0)
            prev_close = ohlc.get("close", ltp) or ltp
            change = round(ltp - prev_close, 2)
            pct = round(change / prev_close * 100, 2) if prev_close else 0
            result[sym] = {
                "last_price": ltp,
                "open": ohlc.get("open", 0),
                "high": ohlc.get("high", 0),
                "low": ohlc.get("low", 0),
                "close": prev_close,
                "volume": v.get("volume", 0),
                "change": change,
                "pct": pct,
            }
        return result
    except Exception:
        return {}


# ── Historical Data ────────────────────────────────────────────────────────

def get_historical_data_bulk(
    symbols: list,
    timeframe: str = "15m",
    max_workers: int = 5,
) -> Dict[str, pd.DataFrame]:
    """
    Fetch OHLCV candles from Kite for multiple symbols in parallel.
    Uses get_instrument_token() per symbol (loads NSE instruments once, then cached).
    Throttles to ~3 req/sec to respect Kite rate limits.
    Returns {symbol: DataFrame}.
    """
    kite = get_kite()
    if not kite:
        return {}

    interval  = _TF_TO_KITE.get(timeframe, "15minute")
    days_back = _TF_DAYS_BACK.get(timeframe, 5)
    now_dt    = datetime.now(IST)
    from_dt   = now_dt - timedelta(days=days_back)
    from_str  = from_dt.strftime("%Y-%m-%d %H:%M:%S")
    to_str    = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    # Pre-load NSE instrument tokens once for all symbols
    _load_instruments("NSE")  # warms the cache used by get_instrument_token()

    _lock = threading.Lock()
    _last_call = [0.0]
    _MIN_INTERVAL = 0.35  # stay under Kite's 3 req/sec limit

    def _fetch_one(sym: str) -> tuple:
        token = get_instrument_token(sym, "NSE")
        if not token:
            return sym, pd.DataFrame()
        with _lock:
            elapsed = time.time() - _last_call[0]
            if elapsed < _MIN_INTERVAL:
                time.sleep(_MIN_INTERVAL - elapsed)
            _last_call[0] = time.time()
        try:
            data = kite.historical_data(token, from_str, to_str, interval,
                                        continuous=False, oi=False)
            if not data:
                return sym, pd.DataFrame()
            df = pd.DataFrame(data).rename(columns={
                "date": "Datetime", "open": "Open", "high": "High",
                "low": "Low", "close": "Close", "volume": "Volume",
            }).set_index("Datetime")
            df.index = pd.to_datetime(df.index)
            return sym, df
        except Exception:
            return sym, pd.DataFrame()

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_fetch_one, s): s for s in symbols}
        try:
            for fut in concurrent.futures.as_completed(futs, timeout=120):
                try:
                    s, df = fut.result()
                    if df is not None and not df.empty:
                        results[s] = df
                except Exception:
                    pass
        except concurrent.futures.TimeoutError:
            pass
    return results


def get_historical_data(
    symbol: str,
    timeframe: str = "5m",
    exchange: str = "NSE",
) -> pd.DataFrame:
    """
    Fetch OHLCV candles from Kite Connect.
    Returns a DataFrame with columns Open/High/Low/Close/Volume indexed by datetime.
    """
    kite = get_kite()
    if not kite:
        return pd.DataFrame()

    token = get_instrument_token(symbol, exchange)
    if not token:
        # Try index token mapping
        idx_map = {
            "NIFTY 50": 256265, "BANK NIFTY": 260105,
            "FIN NIFTY": 257801, "MIDCAP SELECT": 288009,
        }
        token = idx_map.get(symbol)
    if not token:
        return pd.DataFrame()

    interval  = _TF_TO_KITE.get(timeframe, "5minute")
    days_back = _TF_DAYS_BACK.get(timeframe, 5)
    now       = datetime.now(IST)
    from_dt   = now - timedelta(days=days_back)

    try:
        data = kite.historical_data(
            token,
            from_dt.strftime("%Y-%m-%d %H:%M:%S"),
            now.strftime("%Y-%m-%d %H:%M:%S"),
            interval,
            continuous=False,
            oi=False,
        )
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        df = df.rename(columns={
            "date": "Datetime", "open": "Open", "high": "High",
            "low": "Low", "close": "Close", "volume": "Volume",
        })
        df = df.set_index("Datetime")
        if not df.empty:
            df.index = pd.to_datetime(df.index)
        return df
    except Exception:
        return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════
#  ORDER PLACEMENT — Algo Trading
#  Ready for client's algo system. All order types supported.
# ══════════════════════════════════════════════════════════════════════════

def place_order(
    symbol: str,
    exchange: str,
    transaction_type: str,    # "BUY" or "SELL"
    quantity: int,
    order_type: str = "MARKET",   # MARKET | LIMIT | SL | SL-M
    price: float = 0,
    trigger_price: float = 0,
    product: str = "MIS",         # MIS = intraday | NRML = overnight | CNC = delivery
    tag: str = "options_terminal",
) -> dict:
    """
    Place an order via Kite Connect.
    Returns {"order_id": "...", "status": "ok"|"error", "message": "..."}
    """
    kite = get_kite()
    if not kite:
        return {"status": "error", "message": "Kite not initialized"}
    try:
        from kiteconnect import KiteConnect as _KC
        tt = _KC.TRANSACTION_TYPE_BUY if transaction_type.upper() == "BUY" else _KC.TRANSACTION_TYPE_SELL
        ot_map = {
            "MARKET": _KC.ORDER_TYPE_MARKET,
            "LIMIT":  _KC.ORDER_TYPE_LIMIT,
            "SL":     _KC.ORDER_TYPE_SL,
            "SL-M":   _KC.ORDER_TYPE_SLM,
        }
        prod_map = {
            "MIS":  _KC.PRODUCT_MIS,
            "NRML": _KC.PRODUCT_NRML,
            "CNC":  _KC.PRODUCT_CNC,
        }
        order_id = kite.place_order(
            variety=_KC.VARIETY_REGULAR,
            exchange=exchange,
            tradingsymbol=symbol,
            transaction_type=tt,
            quantity=quantity,
            product=prod_map.get(product.upper(), _KC.PRODUCT_MIS),
            order_type=ot_map.get(order_type.upper(), _KC.ORDER_TYPE_MARKET),
            price=price if order_type.upper() == "LIMIT" else None,
            trigger_price=trigger_price if order_type.upper() in ("SL", "SL-M") else None,
            tag=tag,
        )
        return {"status": "ok", "order_id": str(order_id), "message": f"Order placed: {order_id}"}
    except Exception as e:
        return {"status": "error", "order_id": None, "message": str(e)}


def place_option_order(
    symbol: str,           # e.g. "NIFTY"
    strike: float,
    opt_type: str,         # "CE" or "PE"
    expiry_str: str,       # e.g. "27-Mar-2025"
    transaction_type: str, # "BUY" or "SELL"
    quantity: int,
    order_type: str = "MARKET",
    price: float = 0,
    product: str = "MIS",
) -> dict:
    """Place an option order by looking up the NFO tradingsymbol."""
    token = get_nfo_instrument_token(symbol, strike, opt_type, expiry_str)
    if not token:
        return {"status": "error", "message": f"Could not find NFO token for {symbol} {strike} {opt_type} {expiry_str}"}

    # Get tradingsymbol from instruments
    try:
        kite = get_kite()
        rows = kite.instruments("NFO")
        df = pd.DataFrame(rows)
        match = df[df["instrument_token"] == token]
        if match.empty:
            return {"status": "error", "message": "Instrument not found in NFO"}
        nfo_symbol = match.iloc[0]["tradingsymbol"]
    except Exception as e:
        return {"status": "error", "message": str(e)}

    return place_order(
        symbol=nfo_symbol,
        exchange="NFO",
        transaction_type=transaction_type,
        quantity=quantity,
        order_type=order_type,
        price=price,
        product=product,
    )


def modify_order(order_id: str, price: float = 0, quantity: int = 0, trigger_price: float = 0) -> dict:
    """Modify an existing pending order."""
    kite = get_kite()
    if not kite:
        return {"status": "error", "message": "Kite not initialized"}
    try:
        from kiteconnect import KiteConnect as _KC
        kite.modify_order(
            variety=_KC.VARIETY_REGULAR,
            order_id=order_id,
            price=price or None,
            quantity=quantity or None,
            trigger_price=trigger_price or None,
        )
        return {"status": "ok", "message": f"Order {order_id} modified"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def cancel_order(order_id: str) -> dict:
    """Cancel a pending order."""
    kite = get_kite()
    if not kite:
        return {"status": "error", "message": "Kite not initialized"}
    try:
        from kiteconnect import KiteConnect as _KC
        kite.cancel_order(variety=_KC.VARIETY_REGULAR, order_id=order_id)
        return {"status": "ok", "message": f"Order {order_id} cancelled"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Positions & Orders ─────────────────────────────────────────────────────

def get_positions() -> dict:
    """Get current day + net positions."""
    kite = get_kite()
    if not kite:
        return {"day": [], "net": []}
    try:
        return kite.positions()
    except Exception:
        return {"day": [], "net": []}


def get_orders() -> list:
    """Get all orders for the day."""
    kite = get_kite()
    if not kite:
        return []
    try:
        return kite.orders()
    except Exception:
        return []


def get_margins() -> dict:
    """Get available margin (equity segment)."""
    kite = get_kite()
    if not kite:
        return {}
    try:
        return kite.margins()
    except Exception:
        return {}


def get_profile() -> dict:
    """Get logged-in user profile."""
    kite = get_kite()
    if not kite:
        return {}
    try:
        return kite.profile()
    except Exception:
        return {}


# ── Option Chain ───────────────────────────────────────────────────────────

# NFO instrument cache: {underlying_name: [row_dicts]}
_nfo_cache: Dict[str, list] = {}
_nfo_cache_at: float = 0
_NFO_CACHE_TTL = 21600  # 6 hours


_NFO_DISK_CACHE = os.path.expanduser("~/.cache/kite-nfo-instruments.json")


def _get_nfo_instruments(underlying: str) -> list:
    """
    Load all NFO instruments from Kite using raw HTTP (30s timeout) with
    disk cache (6h TTL) so the download only happens once per deployment.
    """
    global _nfo_cache, _nfo_cache_at
    now = time.time()

    # In-memory cache hit
    if _nfo_cache and (now - _nfo_cache_at) < _NFO_CACHE_TTL:
        return _nfo_cache.get(underlying.upper(), [])

    # Try disk cache first
    try:
        if os.path.exists(_NFO_DISK_CACHE):
            age = now - os.path.getmtime(_NFO_DISK_CACHE)
            if age < _NFO_CACHE_TTL:
                with open(_NFO_DISK_CACHE) as f:
                    rows = json.load(f)
                cache: Dict[str, list] = {}
                for r in rows:
                    name = (r.get("name") or "").strip().upper()
                    if name:
                        cache.setdefault(name, []).append(r)
                _nfo_cache = cache
                _nfo_cache_at = now
                print(f"[Kite OC] Loaded {len(rows)} NFO instruments from disk cache")
                return _nfo_cache.get(underlying.upper(), [])
    except Exception as e:
        print(f"[Kite OC] Disk cache read failed: {e}")

    # Download from Kite API directly (raw HTTP, 30s timeout)
    api_key = _kite_api_key()
    access_token = _kite_access_token()
    if not api_key or not access_token:
        print("[Kite OC] No credentials — cannot load NFO instruments")
        return []

    try:
        hdrs = {
            "Authorization": f"token {api_key}:{access_token}",
            "X-Kite-Version": "3",
        }
        resp = _requests.get(
            "https://api.kite.trade/instruments/NFO",
            headers=hdrs,
            timeout=30,
        )
        resp.raise_for_status()
        reader = csv.DictReader(io.StringIO(resp.text))
        rows = list(reader)

        # Save to disk cache
        try:
            os.makedirs(os.path.dirname(_NFO_DISK_CACHE), exist_ok=True)
            with open(_NFO_DISK_CACHE, "w") as f:
                json.dump(rows, f)
        except Exception:
            pass

        cache = {}
        for r in rows:
            name = (r.get("name") or "").strip().upper()
            if name:
                cache.setdefault(name, []).append(r)
        _nfo_cache = cache
        _nfo_cache_at = now
        print(f"[Kite OC] Downloaded {len(rows)} NFO instruments from Kite API")
    except Exception as e:
        print(f"[Kite OC] NFO instrument download failed: {e}")

    return _nfo_cache.get(underlying.upper(), [])


def get_fo_underlying_symbols() -> list:
    """
    Return sorted list of all unique F&O underlying symbols from Kite NFO instruments.
    Triggers NFO instrument download if not already cached.
    Typically ~180-200 symbols: equity stocks + indices (NIFTY, BANKNIFTY, etc.)
    """
    global _nfo_cache
    if not _nfo_cache:
        _get_nfo_instruments("NIFTY")  # loads entire NFO universe into _nfo_cache
    return sorted(_nfo_cache.keys())


def get_option_chain_kite(symbol_nse: str, expiry: str = None) -> Optional[dict]:
    """
    Build a full option chain for symbol_nse using Kite Connect.
    Returns data in NSE format compatible with app.py's option chain renderer:
      {"records": {"expiryDates": [...], "data": [{"strikePrice": ..., "CE": {...}, "PE": {...}}]}}
    Returns None if Kite is not connected or data unavailable.
    """
    kite = get_kite()
    if not kite:
        return None

    # Map NSE symbol names to NFO instrument "name" field
    _nfo_name_map = {
        "NIFTY":      "NIFTY",
        "BANKNIFTY":  "BANKNIFTY",
        "FINNIFTY":   "FINNIFTY",
        "MIDCPNIFTY": "MIDCPNIFTY",
    }
    nfo_name = _nfo_name_map.get(symbol_nse.upper(), symbol_nse.upper())

    contracts = _get_nfo_instruments(nfo_name)
    if not contracts:
        print(f"[Kite OC] No contracts found for {nfo_name}")
        return None

    # expiry field from raw CSV is a string "YYYY-MM-DD"
    # Collect unique expiry strings for CE/PE only
    expiry_set = set()
    for c in contracts:
        itype = (c.get("instrument_type") or "").strip().upper()
        exp = (c.get("expiry") or "").strip()
        if itype in ("CE", "PE") and exp:
            expiry_set.add(exp)

    if not expiry_set:
        print(f"[Kite OC] No expiry dates found for {nfo_name}")
        return None

    sorted_expiries = sorted(expiry_set)  # "YYYY-MM-DD" sorts correctly
    target_expiry = sorted_expiries[0]
    if expiry:
        for e in sorted_expiries:
            if expiry == e or expiry in e:
                target_expiry = e
                break

    # Filter to CE/PE for target expiry
    relevant = [
        c for c in contracts
        if (c.get("instrument_type") or "").strip().upper() in ("CE", "PE")
        and (c.get("expiry") or "").strip() == target_expiry
    ]
    if not relevant:
        print(f"[Kite OC] No contracts for expiry {target_expiry}")
        return None

    print(f"[Kite OC] Building chain for {nfo_name} expiry={target_expiry}, {len(relevant)} contracts")

    # Fetch quotes in batches of 200 (Kite limit)
    token_to_contract = {str(c["instrument_token"]): c for c in relevant}
    all_tokens = list(token_to_contract.keys())
    quotes = {}
    BATCH = 200
    for i in range(0, len(all_tokens), BATCH):
        batch_keys = all_tokens[i:i + BATCH]
        instruments_param = [
            f"NFO:{token_to_contract[t]['tradingsymbol']}" for t in batch_keys
        ]
        try:
            raw = kite.quote(instruments_param)
            quotes.update(raw)
        except Exception as e:
            print(f"[Kite OC] Quote batch failed: {e}")

    # Get spot price
    spot_sym_map = {"NIFTY": "NIFTY 50", "BANKNIFTY": "BANK NIFTY",
                    "FINNIFTY": "FIN NIFTY", "MIDCPNIFTY": "MIDCAP SELECT"}
    spot = get_ltp(spot_sym_map.get(nfo_name, nfo_name), "NSE") or 0

    # Convert expiry "YYYY-MM-DD" → "DD-MON-YYYY" for NSE format
    def _fmt_expiry(e_str):
        try:
            from datetime import datetime as _dt
            return _dt.strptime(e_str, "%Y-%m-%d").strftime("%d-%b-%Y").upper()
        except Exception:
            return e_str

    expiry_fmt = _fmt_expiry(target_expiry)

    # Build NSE-compatible records
    strike_map: Dict[float, dict] = {}
    for token, contract in token_to_contract.items():
        strike = float(contract.get("strike") or 0)
        opt_type = (contract.get("instrument_type") or "").strip().upper()
        ts_key = f"NFO:{contract['tradingsymbol']}"
        q = quotes.get(ts_key, {})
        depth = q.get("depth", {})

        entry = {
            "strikePrice": strike,
            "expiryDate": expiry_fmt,
            "openInterest": q.get("oi", 0),
            "changeinOpenInterest": q.get("oi", 0) - q.get("oi_day_low", 0),
            "lastPrice": q.get("last_price", 0),
            "totalTradedVolume": q.get("volume", 0),
            "impliedVolatility": 0,
            "bidprice": ((depth.get("buy") or [{}])[0] or {}).get("price", 0),
            "askprice": ((depth.get("sell") or [{}])[0] or {}).get("price", 0),
        }

        if strike not in strike_map:
            strike_map[strike] = {"strikePrice": strike, "expiryDate": expiry_fmt}
        strike_map[strike][opt_type] = entry

    if not strike_map:
        print(f"[Kite OC] No quotes returned for {nfo_name}")
        return None

    records_data = sorted(strike_map.values(), key=lambda r: r["strikePrice"])
    expiry_dates_fmt = [_fmt_expiry(e) for e in sorted_expiries]

    print(f"[Kite OC] Built option chain: {len(records_data)} strikes, spot={spot}")
    return {
        "records": {
            "expiryDates": expiry_dates_fmt,
            "data": records_data,
            "underlyingValue": spot,
        },
        "_source": "kite",
    }
