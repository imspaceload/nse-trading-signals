"""
Thin façade over zerodha_api for Kite Connect option chain access.
Token is saved to both kite_token.txt and kite_token.json (via zerodha_api).
"""
import os
import time
from typing import Optional

_TOKEN_TXT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kite_token.txt")


def _save_token_txt(token: str):
    try:
        with open(_TOKEN_TXT, "w") as f:
            f.write(token.strip())
    except Exception as e:
        print(f"[kite_api] Could not write {_TOKEN_TXT}: {e}")


def get_login_url() -> str:
    """Return the Zerodha OAuth login URL."""
    try:
        import zerodha_api as _z
        return _z.get_login_url()
    except Exception as e:
        print(f"[kite_api] get_login_url failed: {e}")
        return ""


def complete_login(request_token: str) -> Optional[str]:
    """
    Exchange a one-time request_token for a persistent access_token.
    Reads KITE_API_SECRET from env at call time (safe even if .env was loaded
    after module import). Saves token to kite_token.txt + kite_token.json.
    Returns the access_token string, or None on failure.
    """
    import zerodha_api as _z
    api_secret = _z._kite_api_secret()
    if not api_secret:
        print("[kite_api] KITE_API_SECRET not set — cannot complete login")
        return None
    kite = _z.get_kite()
    if not kite:
        print("[kite_api] KiteConnect not initialised — check KITE_API_KEY")
        return None
    try:
        data = kite.generate_session(request_token, api_secret=api_secret)
        access_token = data["access_token"]
        kite.set_access_token(access_token)
        from datetime import datetime
        import pytz
        today = datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%Y-%m-%d")
        _z._save_token(access_token, today)
        _save_token_txt(access_token)
        _z._kite_connected = True
        _z._connected_cache = True
        _z._connected_checked_at = time.time()
        print(f"[kite_api] Login complete. Token: {access_token[:8]}...")
        return access_token
    except Exception as e:
        print(f"[kite_api] complete_login failed: {e}")
        return None


def is_connected() -> bool:
    """True if Kite access token is currently valid."""
    try:
        import zerodha_api as _z
        return _z.is_connected()
    except Exception:
        return False


def restore_token() -> bool:
    """
    Restore today's saved token on app startup.
    Tries zerodha_api (Supabase / JSON) first, then kite_token.txt.
    Returns True if a valid token was restored.
    """
    try:
        import zerodha_api as _z
        if _z.restore_saved_token():
            return True
    except Exception:
        pass
    # Fallback: plain-text token file
    try:
        with open(_TOKEN_TXT) as f:
            token = f.read().strip()
        if token:
            import zerodha_api as _z
            kite = _z.get_kite()
            if kite:
                kite.set_access_token(token)
                try:
                    kite.profile()
                    _z._kite_connected = True
                    return True
                except Exception:
                    pass
    except Exception:
        pass
    return False


def get_option_chain_kite(symbol_nse: str, expiry: str = None) -> Optional[dict]:
    """
    Fetch option chain from Kite Connect.
    Returns NSE-format dict (records.data, records.expiryDates, …) or None.
    """
    try:
        import zerodha_api as _z
        return _z.get_option_chain_kite(symbol_nse, expiry=expiry)
    except Exception as e:
        print(f"[kite_api] get_option_chain_kite failed: {e}")
        return None
