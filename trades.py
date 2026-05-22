"""Trade management with persistent JSON storage."""
import json
import uuid
from datetime import datetime
from typing import List, Optional
import pytz

IST = pytz.timezone("Asia/Kolkata")
TRADES_FILE = "trades.json"


def _load_trades() -> list:
    try:
        with open(TRADES_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_trades(trades: list):
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
        "status": "OPEN",
        "created_at": datetime.now(IST).isoformat(),
        "exit_price": None,
        "exit_time": None,
        "pnl": None,
    }
    trades = _load_trades()
    trades.append(trade)
    _save_trades(trades)
    return trade


def close_trade(trade_id: str, exit_price: float) -> Optional[dict]:
    """Close an open trade with an exit price."""
    trades = _load_trades()
    for t in trades:
        if t["id"] == trade_id and t["status"] == "OPEN":
            t["status"] = "CLOSED"
            t["exit_price"] = round(exit_price, 2)
            t["exit_time"] = datetime.now(IST).isoformat()
            # P&L per lot = (exit - entry) * quantity * lot_size
            t["pnl"] = round(
                (exit_price - t["entry_price"]) * t["quantity"] * t["lot_size"], 2
            )
            _save_trades(trades)
            return t
    return None


def get_open_trades() -> List[dict]:
    return [t for t in _load_trades() if t["status"] == "OPEN"]


def get_closed_trades() -> List[dict]:
    return [t for t in _load_trades() if t["status"] == "CLOSED"]


def get_all_trades() -> List[dict]:
    return _load_trades()


def delete_trade(trade_id: str) -> bool:
    """Delete a trade by ID."""
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
