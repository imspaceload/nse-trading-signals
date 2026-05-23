"""SMS broadcast module using Fast2SMS API."""
import os
import json
import requests
from datetime import datetime
from typing import List, Optional
import pytz

IST = pytz.timezone("Asia/Kolkata")

# File-based storage for subscribers and SMS logs
SUBSCRIBERS_FILE = "subscribers.json"
SMS_LOG_FILE = "sms_log.json"

FAST2SMS_API_KEY = os.environ.get("FAST2SMS_API_KEY", "")


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
    return _load_json(SUBSCRIBERS_FILE)


def add_subscriber(phone: str, name: str = "") -> bool:
    subs = get_subscribers()
    phone = _normalize_phone(phone)
    if not phone:
        return False
    for s in subs:
        if s["phone"] == phone:
            return False  # already exists
    subs.append({
        "phone": phone,
        "name": name.strip(),
        "added": datetime.now(IST).isoformat(),
        "active": True,
    })
    _save_json(SUBSCRIBERS_FILE, subs)
    return True


def remove_subscriber(phone: str) -> bool:
    subs = get_subscribers()
    phone = _normalize_phone(phone)
    if not phone:
        return False
    new_subs = [s for s in subs if s["phone"] != phone]
    if len(new_subs) < len(subs):
        _save_json(SUBSCRIBERS_FILE, new_subs)
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


def send_sms_to_all(trade: dict, action: str = "BUY") -> List[dict]:
    """Send SMS to all active subscribers via Fast2SMS. Returns delivery log."""
    subs = [s for s in get_subscribers() if s.get("active", True)]
    if not subs:
        return []

    message_body = _format_trade_sms(trade, action)
    log_entries = []
    now = datetime.now(IST).isoformat()

    if not FAST2SMS_API_KEY:
        # No API key configured — log as failed
        for s in subs:
            log_entries.append({
                "phone": s["phone"],
                "message": message_body,
                "status": "failed",
                "error": "Fast2SMS API key not configured",
                "timestamp": now,
            })
        logs = _load_json(SMS_LOG_FILE)
        logs.extend(log_entries)
        _save_json(SMS_LOG_FILE, logs[-200:])  # keep last 200
        return log_entries

    # Fast2SMS Quick SMS — bulk send to all numbers in one call
    phone_list = ",".join(s["phone"] for s in subs)
    headers = {
        "authorization": FAST2SMS_API_KEY,
        "Content-Type": "application/json",
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
            json=payload,
            headers=headers,
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

    # Save log
    logs = _load_json(SMS_LOG_FILE)
    logs.extend(log_entries)
    _save_json(SMS_LOG_FILE, logs[-200:])
    return log_entries


def get_sms_log() -> List[dict]:
    return _load_json(SMS_LOG_FILE)
