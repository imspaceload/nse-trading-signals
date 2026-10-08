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
import socket
import pandas as pd
import pytz
import urllib3.util.connection as _urllib3_conn

IST = pytz.timezone("Asia/Kolkata")

# Kite only accepts orders from the whitelisted static IP. The droplet has IPv6 too,
# and requests prefers it, so Kite sees an unregistered v6 address — force IPv4.
_urllib3_conn.allowed_gai_family = lambda: socket.AF_INET

from app.core import config

# ── Secrets ────────────────────────────────────────────────────────────────

def _get_secret(key: str, default: str = "") -> str:
    val = os.environ.get(key, "")
    if val:
        return val
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

_TOKEN_FILE = config.data_path("kite_token.json")


def _save_token(access_token: str, login_date: str):
    try:
        from app.services.sms import _get_supabase
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


def _clear_saved_token():
    """Remove the stored token from Supabase and the local JSON file."""
    try:
        from app.services.sms import _get_supabase
        sb = _get_supabase()
        if sb:
            try:
                sb.table("config").delete().in_(
                    "key", ["kite_access_token", "kite_login_date"]
                ).execute()
            except Exception as e:
                print(f"[zerodha] could not clear Supabase token: {e}")
    except Exception:
        pass
    try:
        os.remove(_TOKEN_FILE)
    except OSError:
        pass


def _load_saved_token() -> tuple:
    """Returns (access_token, login_date) or (None, None)."""
    try:
        from app.services.sms import _get_supabase
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
    "1m":  5,
    "3m":  5,
    "5m":  5,
    "15m": 5,
    "30m": 10,
    "1h":  30,
    "1D":  365,
}

# NSE symbol → instrument token cache
_equity_token_cache: Dict[str, int] = {}
_instruments_cache: Dict[str, pd.DataFrame] = {}   # exchange → DataFrame
_instruments_loaded_at: Dict[str, float] = {}       # exchange → timestamp


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


# Cache connected state to avoid a profile() call on every request
_connected_cache: bool = False
_connected_checked_at: float = 0
_last_ok_at: float = 0
_CONNECTED_TTL = 60        # re-validate a working token this often
_DISCONNECTED_TTL = 10     # while disconnected, look for a login made in another process this often
_BLIP_RETRY = 5            # Kite unreachable: re-check this soon...
_BLIP_GRACE = 180          # ...but keep saying "connected" for up to this long since the last good check


def _mark_connected(ok: bool):
    global _connected_cache, _connected_checked_at, _kite_connected, _last_ok_at
    _connected_cache = _kite_connected = ok
    _connected_checked_at = time.time()
    if ok:
        _last_ok_at = _connected_checked_at


def _check_token(kite) -> Optional[bool]:
    """True = token works, False = Kite rejected it (or there is none), None = couldn't ask (network, rate limit)."""
    if not kite.access_token:
        return False
    try:
        kite.profile()
        return True
    except Exception as e:
        from kiteconnect.exceptions import TokenException
        return False if isinstance(e, TokenException) else None


def is_connected() -> bool:
    """
    True if the access token is valid. The API runs several worker processes and the trader worker is another
    one, but the login lands in only one of them — so a missing or rejected token is re-read from storage
    (restore_saved_token) before answering no. A network blip or rate limit is not a logout: the last good
    answer stands for up to _BLIP_GRACE, otherwise the dashboard flickers and the trader stops watching exits.
    """
    global _connected_checked_at
    now = time.time()
    if now - _connected_checked_at < (_CONNECTED_TTL if _connected_cache else _DISCONNECTED_TTL):
        return _connected_cache
    kite = get_kite()
    if not kite:
        return False
    ok = _check_token(kite)
    if ok is None and _connected_cache and now - _last_ok_at < _BLIP_GRACE:
        _connected_checked_at = now - _CONNECTED_TTL + _BLIP_RETRY
        return True
    if ok:
        _mark_connected(True)
    elif not restore_saved_token():   # restore marks connected itself when it works
        _mark_connected(False)
    return _connected_cache


def restore_saved_token() -> bool:
    """Try to restore today's saved token. Returns True if successful."""
    today = datetime.now(IST).strftime("%Y-%m-%d")
    token, login_date = _load_saved_token()
    if token and login_date == today:
        kite = get_kite()
        if kite:
            kite.set_access_token(token)
            if _check_token(kite):
                _mark_connected(True)   # don't let a stale "disconnected" answer linger
                return True
    return False


def disconnect() -> None:
    """Fully log out: invalidate the token at Zerodha, drop it from memory, caches and storage."""
    kite = _kite
    if kite is not None:
        try:
            if kite.access_token:
                kite.invalidate_access_token()
        except Exception as e:
            print(f"[zerodha] invalidate_access_token failed (ignored): {e}")
        kite.set_access_token(None)
    os.environ.pop("KITE_ACCESS_TOKEN", None)
    _mark_connected(False)
    _clear_saved_token()
    try:
        os.remove(config.data_path("kite_token.txt"))
    except OSError:
        pass


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
    api_secret = _kite_api_secret()
    if not kite or not api_secret or not request_token:
        return None
    try:
        data = kite.generate_session(request_token, api_secret=api_secret)
        access_token = data["access_token"]
        kite.set_access_token(access_token)
        today = datetime.now(IST).strftime("%Y-%m-%d")
        _save_token(access_token, today)
        _mark_connected(True)
        return access_token
    except Exception as e:
        print(f"[zerodha] complete_login failed: {e}")
        return None


# ── Instruments ────────────────────────────────────────────────────────────

def _load_instruments(exchange: str = "NSE") -> Optional[pd.DataFrame]:
    """Load instruments CSV from Kite (per-exchange cache, 24h TTL)."""
    global _instruments_cache, _instruments_loaded_at
    now = time.time()
    if exchange in _instruments_cache and (now - _instruments_loaded_at.get(exchange, 0)) < 86400:
        return _instruments_cache[exchange]
    kite = get_kite()
    if not kite:
        return None
    try:
        rows = kite.instruments(exchange)
        _instruments_cache[exchange] = pd.DataFrame(rows)
        _instruments_loaded_at[exchange] = now
        return _instruments_cache[exchange]
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
    max_workers: int = 10,
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
    _MIN_INTERVAL = 0.15  # ~6 req/sec — safe Kite historical API throughput

    _BULK_IDX_TOKENS = {
        "NIFTY 50": 256265, "NIFTY": 256265,
        "BANK NIFTY": 260105, "BANKNIFTY": 260105,
        "FIN NIFTY": 257801, "FINNIFTY": 257801,
        "MIDCAP SELECT": 288009, "MIDCPNIFTY": 288009,
        "INDIA VIX": 264969,
    }

    def _fetch_one(sym: str) -> tuple:
        token = _BULK_IDX_TOKENS.get(sym) or get_instrument_token(sym, "NSE")
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
    days_back: Optional[int] = None,
) -> pd.DataFrame:
    """
    Fetch OHLCV candles from Kite Connect.
    Returns a DataFrame with columns Open/High/Low/Close/Volume indexed by datetime.
    days_back overrides the per-timeframe default lookback (the chart wants more history than the scanner).
    """
    kite = get_kite()
    if not kite:
        return pd.DataFrame()

    # Index token map — covers both app-key names and NSE option-chain symbols
    _IDX_TOKENS = {
        "NIFTY 50":    256265, "NIFTY":       256265,
        "BANK NIFTY":  260105, "BANKNIFTY":   260105, "NIFTY BANK":         260105,
        "FIN NIFTY":   257801, "FINNIFTY":    257801, "NIFTY FIN SERVICE":  257801,
        "MIDCAP SELECT": 288009, "MIDCPNIFTY": 288009, "NIFTY MIDCAP SELECT": 288009,
        "INDIA VIX":   264969,
    }
    token = _IDX_TOKENS.get(symbol) or get_instrument_token(symbol, exchange)
    if not token:
        return pd.DataFrame()

    interval  = _TF_TO_KITE.get(timeframe, "5minute")
    days_back = days_back or _TF_DAYS_BACK.get(timeframe, 5)
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
            price=price if order_type.upper() in ("LIMIT", "SL") else None,
            trigger_price=trigger_price if order_type.upper() in ("SL", "SL-M") else None,
            tag=tag,
            # Zerodha rejects plain MARKET orders on stock options/illiquid contracts;
            # -1 = automatic market protection (only valid for MARKET / SL-M).
            market_protection=-1 if order_type.upper() in ("MARKET", "SL-M") else None,
        )
        return {"status": "ok", "order_id": str(order_id), "message": f"Order placed: {order_id}"}
    except Exception as e:
        return {"status": "error", "order_id": None, "message": str(e)}


def place_and_confirm(*args, timeout: float = 12.0, **kwargs) -> dict:
    """
    place_order() + wait for the exchange/RMS verdict. Kite returns an order id as soon as
    the order is *accepted*; insufficient funds etc. reject it a moment later. Returns
    status "ok" only when shares/lots were actually filled:
      {"status": "ok"|"error", "order_id", "filled_qty", "avg_price", "message"}
    An order still pending after `timeout` is cancelled (any partial fill is kept).
    """
    res = place_order(*args, **kwargs)
    if res.get("status") != "ok":
        return res
    oid = res["order_id"]
    kite = get_kite()
    last = {}
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            hist = kite.order_history(oid) or []
            last = hist[-1] if hist else {}
        except Exception:
            last = {}
        st = str(last.get("status", "")).upper()
        if st in ("COMPLETE", "REJECTED", "CANCELLED"):
            break
        time.sleep(0.7)
    st = str(last.get("status", "")).upper()
    filled = int(last.get("filled_quantity") or 0)
    if st not in ("COMPLETE", "REJECTED", "CANCELLED"):
        cancel_order(oid)                      # still pending — don't leave it working unseen
        try:
            last = (kite.order_history(oid) or [last])[-1]
            filled = int(last.get("filled_quantity") or 0)
        except Exception:
            pass
    if filled > 0:
        return {"status": "ok", "order_id": oid, "filled_qty": filled,
                "avg_price": float(last.get("average_price") or 0),
                "message": f"Filled {filled}"}
    why = last.get("status_message") or last.get("status") or "no fill / timed out"
    return {"status": "error", "order_id": oid, "filled_qty": 0, "avg_price": 0,
            "message": f"Order {oid} not filled: {why}"}


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


def get_account_pnl() -> Optional[float]:
    """
    Account-wide P&L as Kite's Positions page shows it ("Total P&L"): the sum of
    `pnl` over net positions, so it includes trades placed outside the bot.
    None when the call fails, so callers can fall back instead of showing 0.
    """
    kite = get_kite()
    if not kite:
        return None
    try:
        net = (kite.positions() or {}).get("net", []) or []
    except Exception as e:
        print(f"[kite-debug] positions() failed, P&L falls back to bot ledger: {e}", flush=True)
        return None
    return sum(float(p.get("pnl") or 0) for p in net)


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


def get_available_funds() -> float:
    """
    Spendable equity funds. Kite reports the balance under several fields
    (cash = settled cash, live_balance = cash incl. today's pay-in/uses,
    net = total after utilisation). A deposit made today can show up in
    live_balance/net before it does in cash, so take the largest of them.
    Raw response is printed for debugging.
    """
    eq = (get_margins() or {}).get("equity", {}) or {}
    avail = eq.get("available", {}) or {}
    print(f"[kite-debug] margins equity: net={eq.get('net')} available={avail} utilised={eq.get('utilised')}", flush=True)
    vals = [avail.get("cash"), avail.get("live_balance"), eq.get("net")]
    return max([float(v) for v in vals if isinstance(v, (int, float))] or [0.0])


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

_CASH_SETTLED = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX"}
STOCK_OPTION_ROLL_DAYS = 7


def _tradable_expiry(symbol: str, expiries):
    """Nearest expiry we can open fresh longs in (see STOCK_OPTION_ROLL_DAYS)."""
    today = datetime.now(IST).date()
    live = sorted(e for e in set(expiries) if e >= today)
    if symbol.upper() not in _CASH_SETTLED:
        later = [e for e in live if (e - today).days > STOCK_OPTION_ROLL_DAYS]
        if later:
            return later[0]
    return live[0] if live else None


def get_option_strikes(symbol: str) -> List[float]:
    """Listed strikes of the expiry pick_atm_option trades. Empty if unknown / logged out."""
    today = datetime.now(IST).date()
    by_expiry: Dict = {}
    for r in _get_nfo_instruments(symbol):
        if (r.get("instrument_type") or "").upper() not in ("CE", "PE"):
            continue
        try:
            exp = datetime.strptime(r["expiry"], "%Y-%m-%d").date()
            if exp >= today:
                by_expiry.setdefault(exp, set()).add(float(r["strike"]))
        except Exception:
            continue
    exp = _tradable_expiry(symbol, by_expiry)
    return sorted(by_expiry[exp]) if exp else []


def pick_atm_option(symbol: str, spot: float, opt_type: str) -> Optional[dict]:
    """
    Pick the nearest tradable expiry (_tradable_expiry), nearest-ATM option contract for a stock/index.
    Used by the auto-trader (auto_trader.py) to enter CE/PE positions off
    scanner signals without needing a strike/expiry picked by hand.
    Returns {"tradingsymbol","strike","type","expiry","lot_size",
             "instrument_token","ltp"} or None if no contract / no LTP found.
    """
    if spot is None or spot <= 0:
        return None
    rows = _get_nfo_instruments(symbol)
    if not rows:
        return None
    opt_type = opt_type.upper()
    today = datetime.now(IST).date()

    candidates = []
    for r in rows:
        if (r.get("instrument_type") or "").upper() != opt_type:
            continue
        try:
            exp = datetime.strptime(r["expiry"], "%Y-%m-%d").date()
        except Exception:
            continue
        if exp < today:
            continue
        try:
            strike = float(r["strike"])
        except Exception:
            continue
        candidates.append((exp, strike, r))
    if not candidates:
        return None

    target_expiry = _tradable_expiry(symbol, (c[0] for c in candidates))
    same_expiry = [c for c in candidates if c[0] == target_expiry]
    same_expiry.sort(key=lambda c: abs(c[1] - spot))
    exp, strike, row = same_expiry[0]

    tsym = row["tradingsymbol"]
    try:
        lot_size = int(float(row.get("lot_size", 0)))
        token = int(float(row.get("instrument_token", 0)))
    except Exception:
        return None
    if lot_size <= 0 or not token:
        return None

    ltp = get_ltp(tsym, exchange="NFO")
    if not ltp:
        return None

    return {
        "tradingsymbol": tsym,
        "strike": strike,
        "type": opt_type,
        "expiry": exp.isoformat(),
        "lot_size": lot_size,
        "instrument_token": token,
        "ltp": ltp,
    }


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

        # Kite's quote API has no previous-close OI, only today's day-high/day-low OI.
        # Using oi - oi_day_low is always >= 0 and can never show OI unwinding, so
        # center on today's OI range instead — lets the change swing negative too.
        _oi_now = q.get("oi", 0)
        _oi_mid = (q.get("oi_day_high", _oi_now) + q.get("oi_day_low", _oi_now)) / 2

        entry = {
            "strikePrice": strike,
            "expiryDate": expiry_fmt,
            "openInterest": _oi_now,
            "changeinOpenInterest": round(_oi_now - _oi_mid),
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
