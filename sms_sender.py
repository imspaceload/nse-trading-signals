"""SMS broadcast module using Twilio API."""
import os
import json
from datetime import datetime
from typing import List, Optional
import pytz

IST = pytz.timezone("Asia/Kolkata")

# File-based storage for subscribers and SMS logs
SUBSCRIBERS_FILE = "subscribers.json"
SMS_LOG_FILE = "sms_log.json"

TWILIO_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.environ.get("TWILIO_FROM_NUMBER", "")


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
    phone = phone.strip()
    if not phone.startswith("+"):
        phone = "+91" + phone.lstrip("0")
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
    phone = phone.strip()
    if not phone.startswith("+"):
        phone = "+91" + phone.lstrip("0")
    new_subs = [s for s in subs if s["phone"] != phone]
    if len(new_subs) < len(subs):
        _save_json(SUBSCRIBERS_FILE, new_subs)
        return True
    return False


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
    """Send SMS to all active subscribers. Returns delivery log."""
    subs = [s for s in get_subscribers() if s.get("active", True)]
    if not subs:
        return []

    message_body = _format_trade_sms(trade, action)
    log_entries = []
    now = datetime.now(IST).isoformat()

    if not TWILIO_SID or not TWILIO_AUTH or not TWILIO_FROM:
        # No Twilio configured — log as failed
        for s in subs:
            log_entries.append({
                "phone": s["phone"],
                "message": message_body,
                "status": "failed",
                "error": "Twilio not configured",
                "timestamp": now,
            })
        logs = _load_json(SMS_LOG_FILE)
        logs.extend(log_entries)
        _save_json(SMS_LOG_FILE, logs[-200:])  # keep last 200
        return log_entries

    try:
        from twilio.rest import Client
        client = Client(TWILIO_SID, TWILIO_AUTH)
    except ImportError:
        for s in subs:
            log_entries.append({
                "phone": s["phone"],
                "message": message_body,
                "status": "failed",
                "error": "twilio package not installed",
                "timestamp": now,
            })
        logs = _load_json(SMS_LOG_FILE)
        logs.extend(log_entries)
        _save_json(SMS_LOG_FILE, logs[-200:])
        return log_entries

    for s in subs:
        try:
            msg = client.messages.create(
                body=message_body,
                from_=TWILIO_FROM,
                to=s["phone"],
            )
            log_entries.append({
                "phone": s["phone"],
                "message": message_body,
                "status": msg.status,
                "sid": msg.sid,
                "timestamp": now,
            })
        except Exception as e:
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
