"""Trade management with Supabase persistence (JSON fallback)."""
import json
import os
import uuid
from datetime import datetime
from typing import List, Optional
import pytz

IST = pytz.timezone("Asia/Kolkata")
TRADES_FILE = "trades.json"

# ── Supabase setup (same pattern as sms_sender.py) ──

def _get_secret(key: str) -> str:
    val = os.environ.get(key, "")
    if val:
        return val
    try:
        import streamlit as st
        return st.secrets.get(key, "")
    except Exception:
        return ""

_supabase_client = None

def _get_supabase():
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    url = _get_secret("SUPABASE_URL")
    key = _get_secret("SUPABASE_KEY")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        _supabase_client = create_client(url, key)
        return _supabase_client
    except Exception:
        return None


# ── JSON fallback ──

def _load_trades() -> list:
    sb = _get_supabase()
    if sb:
        try:
            resp = sb.table("trades").select("*").execute()
            return resp.data if resp.data else []
        except Exception:
            pass
    try:
        with open(TRADES_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_trades(trades: list):
    # JSON fallback only — Supabase uses direct insert/update
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2, default=str)


def create_trade(
    instrument: str,
    strike: float,
    option_type: str,
    expiry: str,
    entry_price: float,
    target_price: float,
    stop_loss: float,
    quantity: int = 1,
    lot_size: int = 1,
) -> dict:
    """Create a new trade and persist it."""
    trade = {
        "id": str(uuid.uuid4())[:8],
        "instrument": instrument,
        "strike": strike,
        "option_type": option_type,
        "expiry": expiry,
        "entry_price": round(entry_price, 2),
        "target_price": round(target_price, 2),
        "stop_loss": round(stop_loss, 2),
        "quantity": quantity,
        "lot_size": lot_size,
        "averaging_price": round(entry_price * 0.7, 2),  # default 30% below entry
        "status": "OPEN",
        "created_at": datetime.now(IST).isoformat(),
        "exit_price": None,
        "exit_time": None,
        "pnl": None,
    }
    sb = _get_supabase()
    if sb:
        try:
            sb.table("trades").insert(trade).execute()
            return trade
        except Exception:
            pass
    # Fallback: JSON
    trades = _load_trades()
    trades.append(trade)
    _save_trades(trades)
    return trade


def close_trade(trade_id: str, exit_price: float) -> Optional[dict]:
    """Close an open trade with an exit price."""
    sb = _get_supabase()
    if sb:
        try:
            resp = sb.table("trades").select("*").eq("id", trade_id).eq("status", "OPEN").execute()
            if resp.data:
                t = resp.data[0]
                pnl = round(
                    (exit_price - t["entry_price"]) * t["quantity"] * t.get("lot_size", 1), 2
                )
                sb.table("trades").update({
                    "status": "CLOSED",
                    "exit_price": round(exit_price, 2),
                    "exit_time": datetime.now(IST).isoformat(),
                    "pnl": pnl,
                }).eq("id", trade_id).execute()
                t["status"] = "CLOSED"
                t["exit_price"] = round(exit_price, 2)
                t["exit_time"] = datetime.now(IST).isoformat()
                t["pnl"] = pnl
                return t
            return None
        except Exception:
            pass
    # Fallback: JSON
    trades = _load_trades()
    for t in trades:
        if t["id"] == trade_id and t["status"] == "OPEN":
            t["status"] = "CLOSED"
            t["exit_price"] = round(exit_price, 2)
            t["exit_time"] = datetime.now(IST).isoformat()
            t["pnl"] = round(
                (exit_price - t["entry_price"]) * t["quantity"] * t.get("lot_size", 1), 2
            )
            _save_trades(trades)
            return t
    return None


def get_open_trades() -> List[dict]:
    sb = _get_supabase()
    if sb:
        try:
            resp = sb.table("trades").select("*").eq("status", "OPEN").execute()
            return resp.data if resp.data else []
        except Exception:
            pass
    return [t for t in _load_trades() if t["status"] == "OPEN"]


def get_closed_trades() -> List[dict]:
    sb = _get_supabase()
    if sb:
        try:
            resp = sb.table("trades").select("*").eq("status", "CLOSED").order("exit_time", desc=True).execute()
            return resp.data if resp.data else []
        except Exception:
            pass
    return [t for t in _load_trades() if t["status"] == "CLOSED"]


def get_all_trades() -> List[dict]:
    return _load_trades()


def delete_trade(trade_id: str) -> bool:
    """Delete a trade by ID."""
    sb = _get_supabase()
    if sb:
        try:
            existing = sb.table("trades").select("id").eq("id", trade_id).execute()
            if existing.data:
                sb.table("trades").delete().eq("id", trade_id).execute()
                return True
            return False
        except Exception:
            pass
    # Fallback: JSON
    trades = _load_trades()
    new_trades = [t for t in trades if t["id"] != trade_id]
    if len(new_trades) < len(trades):
        _save_trades(new_trades)
        return True
    return False


def format_trade_display(trade: dict) -> str:
    """Human-readable trade string.
    e.g. BUY RELIANCE 1400 CE (29-May) @ Rs.35 -> Target Rs.45 | SL Rs.25 | Qty 1 lot
    """
    action = "BUY" if trade["status"] == "OPEN" else "CLOSED"
    s = (
        f"{action}: {trade['instrument']} {int(trade['strike'])} {trade['option_type']} "
        f"({trade['expiry']}) "
        f"@ Rs.{trade['entry_price']:,.2f} "
        f"-> Target Rs.{trade['target_price']:,.2f} | "
        f"SL Rs.{trade['stop_loss']:,.2f} | "
        f"Qty {trade['quantity']} lot"
    )
    if trade["status"] == "CLOSED" and trade["exit_price"] is not None:
        sign = "+" if trade["pnl"] >= 0 else ""
        s += f" | Exit Rs.{trade['exit_price']:,.2f} | P&L {sign}Rs.{trade['pnl']:,.2f}"
    return s
