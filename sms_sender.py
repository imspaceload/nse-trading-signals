"""SMS broadcast module using Fast2SMS API + Supabase for persistent storage."""
import os
import json
import requests
from datetime import datetime
from typing import List, Optional
import pytz

IST = pytz.timezone("Asia/Kolkata")

def _get_secret(key: str) -> str:
    """Read secret from env var or Streamlit secrets."""
    val = os.environ.get(key, "")
    if val:
        return val
    try:
        import streamlit as st
        return st.secrets.get(key, "")
    except Exception:
        return ""

FAST2SMS_API_KEY = _get_secret("FAST2SMS_API_KEY")
SUPABASE_URL = _get_secret("SUPABASE_URL")
SUPABASE_KEY = _get_secret("SUPABASE_KEY")

# Lazy-initialized Supabase client
_supabase_client = None


def _get_supabase():
    """Lazy init Supabase client. Returns None if not configured."""
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    try:
        from supabase import create_client
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        return _supabase_client
    except Exception:
        return None


# ── Fallback: JSON file storage (used when Supabase not configured) ──

def _load_json(path: str) -> list:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_json(path: str, data: list):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


# ── Subscriber Management ──

def get_subscribers() -> List[dict]:
    sb = _get_supabase()
    if sb:
        try:
            resp = sb.table("subscribers").select("*").execute()
            rows = resp.data if resp.data else []
            # Filter active in Python (handles both bool and string "true")
            return [r for r in rows if r.get("active") in (True, "true", "True")]
        except Exception:
            pass  # fall through to JSON
    return _load_json("subscribers.json")


def add_subscriber(phone: str, name: str = "") -> bool:
    phone = _normalize_phone(phone)
    if not phone:
        return False

    sb = _get_supabase()
    if sb:
        try:
            # Check if already exists
            existing = sb.table("subscribers").select("phone").eq("phone", phone).execute()
            if existing.data:
                return False
            sb.table("subscribers").insert({
                "phone": phone,
                "name": name.strip(),
                "added": datetime.now(IST).isoformat(),
                "active": True,
            }).execute()
            return True
        except Exception:
            return False

    # Fallback: JSON
    subs = _load_json("subscribers.json")
    for s in subs:
        if s["phone"] == phone:
            return False
    subs.append({
        "phone": phone,
        "name": name.strip(),
        "added": datetime.now(IST).isoformat(),
        "active": True,
    })
    _save_json("subscribers.json", subs)
    return True


def remove_subscriber(phone: str) -> bool:
    phone = _normalize_phone(phone)
    if not phone:
        return False

    sb = _get_supabase()
    if sb:
        try:
            existing = sb.table("subscribers").select("phone").eq("phone", phone).execute()
            if not existing.data:
                return False
            sb.table("subscribers").delete().eq("phone", phone).execute()
            return True
        except Exception:
            return False

    # Fallback: JSON
    subs = _load_json("subscribers.json")
    new_subs = [s for s in subs if s["phone"] != phone]
    if len(new_subs) < len(subs):
        _save_json("subscribers.json", new_subs)
        return True
    return False


def _normalize_phone(phone: str) -> str:
    """Normalize to 10-digit Indian mobile number (Fast2SMS format)."""
    phone = phone.strip().lstrip("+")
    if phone.startswith("91") and len(phone) == 12:
        phone = phone[2:]
    phone = phone.lstrip("0")
    if len(phone) == 10 and phone.isdigit():
        return phone
    return ""


# ── SMS Sending ──

def _format_trade_sms(trade: dict, action: str = "BUY") -> str:
    """Format a trade signal into an SMS under 160 chars."""
    symbol = trade.get("instrument", "")
    strike = trade.get("strike", "")
    opt_type = trade.get("option_type", "CE")
    expiry = trade.get("expiry", "")
    entry = trade.get("entry_price", 0)
    target = trade.get("target_price", 0)
    sl = trade.get("stop_loss", 0)
    qty = trade.get("quantity", 1)

    if action == "EXIT":
        exit_price = trade.get("exit_price", 0)
        pnl = trade.get("pnl", 0)
        sign = "+" if pnl >= 0 else ""
        return f"EXIT: {symbol} {strike} {opt_type} | Exit: {exit_price} | P&L: {sign}{pnl}"

    msg = f"BUY: {symbol} {strike} {opt_type}"
    if expiry:
        msg += f" | Exp: {expiry}"
    msg += f" | Entry: {entry}"
    if target:
        msg += f" | T: {target}"
    if sl:
        msg += f" | SL: {sl}"
    if qty > 1:
        msg += f" | Qty: {qty}lot"
    return msg[:160]


def _log_sms(log_entries: List[dict]):
    """Persist SMS log entries to Supabase or JSON fallback."""
    sb = _get_supabase()
    if sb:
        try:
            sb.table("sms_log").insert(log_entries).execute()
            return
        except Exception:
            pass  # fall through to JSON

    logs = _load_json("sms_log.json")
    logs.extend(log_entries)
    _save_json("sms_log.json", logs[-200:])


def send_sms_to_all(trade: dict, action: str = "BUY") -> List[dict]:
    """Send SMS to all active subscribers via Fast2SMS. Returns delivery log."""
    subs = [s for s in get_subscribers() if s.get("active", True)]
    if not subs:
        return []

    message_body = _format_trade_sms(trade, action)
    log_entries = []
    now = datetime.now(IST).isoformat()

    if not FAST2SMS_API_KEY:
        for s in subs:
            log_entries.append({
                "phone": s["phone"],
                "message": message_body,
                "status": "failed",
                "error": "Fast2SMS API key not configured",
                "timestamp": now,
            })
        _log_sms(log_entries)
        return log_entries

    # Fast2SMS Quick SMS (route q) — no DLT registration needed
    phone_list = ",".join(s["phone"] for s in subs)
    headers = {
        "authorization": FAST2SMS_API_KEY,
    }
    payload = {
        "route": "q",
        "message": message_body,
        "language": "english",
        "flash": 0,
        "numbers": phone_list,
    }

    try:
        resp = requests.post(
            "https://www.fast2sms.com/dev/bulkV2",
            headers=headers,
            json=payload,
            timeout=30,
        )
        result = resp.json()
        api_ok = result.get("return", False)
        api_status = "sent" if api_ok else "failed"
        api_msg = result.get("message", "")
        if isinstance(api_msg, list):
            api_msg = api_msg[0] if api_msg else ""
        request_id = result.get("request_id", "")

        for s in subs:
            log_entries.append({
                "phone": s["phone"],
                "message": message_body,
                "status": api_status,
                "request_id": request_id,
                "api_response": str(api_msg)[:100],
                "timestamp": now,
            })
    except Exception as e:
        for s in subs:
            log_entries.append({
                "phone": s["phone"],
                "message": message_body,
                "status": "failed",
                "error": str(e)[:100],
                "timestamp": now,
            })

    _log_sms(log_entries)
    return log_entries


def get_sms_log() -> List[dict]:
    sb = _get_supabase()
    if sb:
        try:
            resp = sb.table("sms_log").select("*").order("timestamp", desc=True).limit(200).execute()
            return resp.data if resp.data else []
        except Exception:
            return []
    return _load_json("sms_log.json")
