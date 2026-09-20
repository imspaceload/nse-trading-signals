"""
Module A — Automated Trade Executor
Averaging-down algo with NO stop-loss: auto-enters on scanner BUY signals,
averages down on configured price drops, and exits only when the profit
target is hit. Everything else (max trades, margin caps, dedup) is a guard
rail around that core loop.

Design note: evaluation is driven by app.py's own Streamlit autorefresh
cycle (~30s while the market is open) rather than a standalone background
process/websocket. That keeps the auto-trader's cadence identical to the
rest of the dashboard (same cadence the existing "auto signal -> SMS"
feature in the Chart tab already uses) and avoids running a second broker
session/thread pool alongside the Streamlit server. If you need sub-second
reaction to price moves, swap `_check_exits_and_averaging`'s quote source
for a KiteTicker subscription — the position/order logic below doesn't care
where the price tick came from.

NO stop-loss by design (per spec): a losing position is never auto-closed.
It only exits on a profit-target hit, an "Exit Now" click, or the user
manually squaring it off in Kite. This means a position CAN sit at an
unbounded loss if price keeps falling past max averaging rounds — the
'Max Margin Per Trade' and 'Max Averaging Rounds' caps are the only ceiling
on how much capital that can consume.
"""
import json
import os
import threading
import uuid
from datetime import datetime
from typing import Dict, List, Optional

import pytz

import zerodha_api
from data_fetcher import is_market_open

IST = pytz.timezone("Asia/Kolkata")

CONFIG_FILE = "auto_trader_config.json"
POSITIONS_FILE = "auto_trader_positions.json"

DEDUP_SECONDS = 60  # never fire two orders for the same position within this window

DEFAULT_CONFIG = {
    "id": 1,
    "total_capital": 100000.0,
    "max_margin_pct": 20.0,        # % of total capital allowed per single trade
    "max_active_trades": 2,
    "profit_target_pct": 10.0,     # % of deployed capital -> auto exit
    "averaging_drop_pct": 5.0,     # price drop % below avg price -> next buy
    "max_averaging_rounds": 3,
    "trade_mode": "OPTIONS",       # OPTIONS | EQUITY
    "trade_paused": False,
}

# Guards every read-modify-write across a single Streamlit process so two
# concurrent sessions/reruns can't both act on the same signal/position.
_engine_lock = threading.RLock()


# ── Secrets / Supabase (same pattern as trades.py / sms_sender.py) ─────────

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


# ── Config persistence ──────────────────────────────────────────────────────

_config_cache: Optional[dict] = None


def get_config() -> dict:
    global _config_cache
    with _engine_lock:
        if _config_cache is not None:
            return dict(_config_cache)
        cfg = None
        sb = _get_supabase()
        if sb:
            try:
                resp = sb.table("auto_trader_config").select("*").eq("id", 1).execute()
                if resp.data:
                    cfg = resp.data[0]
            except Exception:
                pass
        if cfg is None:
            try:
                with open(CONFIG_FILE) as f:
                    cfg = json.load(f)
            except Exception:
                cfg = {}
        merged = dict(DEFAULT_CONFIG)
        merged.update({k: v for k, v in cfg.items() if v is not None})
        merged["id"] = 1
        _config_cache = merged
        return dict(merged)


def set_config(**kwargs) -> dict:
    """Partial update — only keys passed are changed."""
    with _engine_lock:
        cfg = get_config()
        cfg.update({k: v for k, v in kwargs.items() if v is not None})
        cfg["id"] = 1
        sb = _get_supabase()
        if sb:
            try:
                sb.table("auto_trader_config").upsert(cfg).execute()
            except Exception:
                pass
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass
        global _config_cache
        _config_cache = cfg
        return dict(cfg)


# ── Position persistence ────────────────────────────────────────────────────

def _load_all_positions() -> List[dict]:
    sb = _get_supabase()
    if sb:
        try:
            resp = sb.table("auto_trader_positions").select("*").order("created_at", desc=True).execute()
            return resp.data if resp.data else []
        except Exception:
            pass
    try:
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def _save_all_positions_fallback(rows: List[dict]):
    try:
        with open(POSITIONS_FILE, "w") as f:
            json.dump(rows, f, indent=2, default=str)
    except Exception:
        pass


def get_positions(status: Optional[str] = None) -> List[dict]:
    rows = _load_all_positions()
    if status:
        rows = [r for r in rows if r.get("status") == status]
    return rows


def _create_position(pos: dict) -> dict:
    sb = _get_supabase()
    if sb:
        try:
            sb.table("auto_trader_positions").insert(pos).execute()
            return pos
        except Exception:
            pass
    rows = _load_all_positions()
    rows.append(pos)
    _save_all_positions_fallback(rows)
    return pos


def _update_position(position_id: str, **fields) -> Optional[dict]:
    sb = _get_supabase()
    if sb:
        try:
            sb.table("auto_trader_positions").update(fields).eq("id", position_id).execute()
            resp = sb.table("auto_trader_positions").select("*").eq("id", position_id).execute()
            return resp.data[0] if resp.data else None
        except Exception:
            pass
    rows = _load_all_positions()
    for r in rows:
        if r["id"] == position_id:
            r.update(fields)
            _save_all_positions_fallback(rows)
            return r
    return None


# ── Dashboard helpers (live API pull — safe to call on every Streamlit rerun,
#    independent of the engine tick that runs in the Scanner tab) ───────────

def refresh_open_position_prices() -> List[dict]:
    """
    Pull live LTP for every OPEN position and update current_price/pnl/pnl_pct.
    Display-only — never places an order. Call this from the Auto Trader tab
    itself so the table is fresh even if you never visit the Scanner tab
    (which is what actually drives entries/averaging/exits).
    """
    open_positions = get_positions(status="OPEN")
    if not open_positions or not zerodha_api.is_connected():
        return open_positions

    by_exchange: Dict[str, List[str]] = {}
    for p in open_positions:
        by_exchange.setdefault(p["exchange"], []).append(p["tradingsymbol"])

    quotes = {}
    for exch, syms in by_exchange.items():
        try:
            quotes.update(zerodha_api.get_quotes(list(set(syms)), exchange=exch))
        except Exception:
            pass

    refreshed = []
    for p in open_positions:
        q = quotes.get(p["tradingsymbol"])
        if q and q.get("last_price"):
            cur = q["last_price"]
            deployed = p["avg_price"] * p["total_qty"]
            pnl = (cur - p["avg_price"]) * p["total_qty"]
            pnl_pct = (pnl / deployed * 100) if deployed else 0
            updated = _update_position(
                p["id"], current_price=round(cur, 2),
                pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 2),
            )
            refreshed.append(updated or p)
        else:
            refreshed.append(p)
    return refreshed


def get_dashboard_summary() -> dict:
    """
    Capital bar numbers. Deployed/P&L come from our own position ledger
    (that's the actual cost basis of what the bot bought); Available is
    pulled live from Kite's margins API when connected, since that reflects
    real broker-side cash rather than our own capital bookkeeping — the two
    can diverge if margin is used elsewhere in the same account.
    """
    cfg = get_config()
    open_positions = get_positions(status="OPEN")
    deployed = sum(p["avg_price"] * p["total_qty"] for p in open_positions)
    pnl_open = sum(p.get("pnl", 0) or 0 for p in open_positions)

    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    closed_today = [
        p for p in get_positions(status="CLOSED")
        if (p.get("closed_at") or "").startswith(today_str)
    ]
    pnl_closed_today = sum(c.get("pnl", 0) or 0 for c in closed_today)

    total_capital = cfg["total_capital"]
    live_cash = _available_cash() if zerodha_api.is_connected() else 0
    available = live_cash if live_cash else max(total_capital - deployed, 0)

    return {
        "total_capital": total_capital,
        "deployed": round(deployed, 2),
        "available": round(available, 2),
        "available_is_live": bool(live_cash),
        "pnl_today": round(pnl_open + pnl_closed_today, 2),
        "open_count": len(open_positions),
        "max_active_trades": cfg["max_active_trades"],
    }


def past_square_off_warning_time() -> bool:
    """True after 3:15 PM IST — dashboard should show the no-auto-square-off warning."""
    now = datetime.now(IST)
    return (now.hour, now.minute) >= (15, 15)


# ── Order sizing ─────────────────────────────────────────────────────────────

def _available_cash() -> float:
    try:
        margins = zerodha_api.get_margins()
        avail = margins.get("equity", {}).get("available", {})
        return float(avail.get("cash", 0) or avail.get("live_balance", 0) or 0)
    except Exception:
        return 0.0


def _recently_ordered(pos: dict) -> bool:
    last = pos.get("last_order_at")
    if not last:
        return False
    try:
        fired = datetime.fromisoformat(last)
        if fired.tzinfo is None:
            fired = IST.localize(fired)
        return (datetime.now(IST) - fired).total_seconds() < DEDUP_SECONDS
    except Exception:
        return False


# ── Entries ──────────────────────────────────────────────────────────────────

def _enter_trade(nse_symbol: str, spot: float, cfg: dict) -> Optional[dict]:
    max_trade_capital = cfg["total_capital"] * cfg["max_margin_pct"] / 100.0
    if max_trade_capital <= 0:
        return None

    available = _available_cash()
    if available and available < max_trade_capital * 0.1:
        print(f"[auto_trader] skip entry {nse_symbol}: available margin too low ({available})")
        return None

    if cfg["trade_mode"] == "OPTIONS":
        opt = zerodha_api.pick_atm_option(nse_symbol, spot, "CE")
        if not opt or not opt.get("ltp"):
            print(f"[auto_trader] skip entry {nse_symbol}: no ATM CE contract/LTP found")
            return None
        lot_size = opt["lot_size"]
        lots = max(1, int(max_trade_capital // (opt["ltp"] * lot_size)))
        qty = lots * lot_size
        exchange, tradingsymbol, option_type = "NFO", opt["tradingsymbol"], "CE"
        product = "NRML"
        entry_price = opt["ltp"]
        instrument_token = opt["instrument_token"]
    else:
        if spot <= 0:
            return None
        qty = max(1, int(max_trade_capital // spot))
        exchange, tradingsymbol, option_type = "NSE", nse_symbol, None
        product = "CNC"
        entry_price = spot
        instrument_token = zerodha_api.get_instrument_token(nse_symbol, "NSE")

    if available and qty * entry_price > available:
        print(f"[auto_trader] skip entry {nse_symbol}: order size {qty*entry_price:.0f} exceeds available margin {available:.0f}")
        return None

    order = zerodha_api.place_order(
        symbol=tradingsymbol, exchange=exchange, transaction_type="BUY",
        quantity=qty, order_type="MARKET", product=product, tag="auto_trader",
    )
    if order.get("status") != "ok":
        print(f"[auto_trader] entry order FAILED {nse_symbol}: {order.get('message')}")
        return None

    now_iso = datetime.now(IST).isoformat()
    pos = {
        "id": str(uuid.uuid4())[:8],
        "symbol": nse_symbol,
        "exchange": exchange,
        "trade_mode": cfg["trade_mode"],
        "option_type": option_type,
        "tradingsymbol": tradingsymbol,
        "instrument_token": instrument_token,
        "qty_per_round": qty,
        "total_qty": qty,
        "entry_price": round(entry_price, 2),
        "avg_price": round(entry_price, 2),
        "current_price": round(entry_price, 2),
        "rounds": 1,
        "status": "OPEN",
        "paused_averaging": False,
        "last_order_at": now_iso,
        "pnl": 0.0,
        "pnl_pct": 0.0,
        "orders": [{
            "order_id": order["order_id"], "side": "BUY", "qty": qty,
            "price": round(entry_price, 2), "round": 1, "at": now_iso,
        }],
        "created_at": now_iso,
        "closed_at": None,
        "exit_reason": None,
    }
    _create_position(pos)
    print(f"[auto_trader] ENTERED {nse_symbol} {tradingsymbol} x{qty} @ {entry_price}")
    return pos


def _check_new_entries(scan_data: dict, cfg: dict):
    open_positions = get_positions(status="OPEN")
    if len(open_positions) >= cfg["max_active_trades"]:
        return
    slots = cfg["max_active_trades"] - len(open_positions)
    open_symbols = {p["symbol"] for p in open_positions}

    candidates = [
        (sym, v) for sym, v in scan_data.items()
        if v.get("signal") == "BUY" and sym not in open_symbols and v.get("spot")
    ]
    # Strongest BUY signals first (most confirming indicators)
    candidates.sort(key=lambda kv: -(kv[1].get("buy_count") or 0))

    for sym, v in candidates[:slots]:
        try:
            _enter_trade(sym, v["spot"], cfg)
        except Exception as e:
            print(f"[auto_trader] entry error for {sym}: {e}")


# ── Averaging / exits ────────────────────────────────────────────────────────

def _average_down(pos: dict, cur_price: float, cfg: dict):
    cost_basis = pos["avg_price"] * pos["total_qty"]
    added_capital = cur_price * pos["qty_per_round"]
    max_trade_capital = cfg["total_capital"] * cfg["max_margin_pct"] / 100.0

    if cost_basis + added_capital > max_trade_capital:
        print(f"[auto_trader] skip averaging {pos['symbol']}: would exceed per-trade margin cap")
        return

    available = _available_cash()
    if available and available < added_capital:
        print(f"[auto_trader] skip averaging {pos['symbol']}: insufficient available margin")
        return

    order = zerodha_api.place_order(
        symbol=pos["tradingsymbol"], exchange=pos["exchange"], transaction_type="BUY",
        quantity=pos["qty_per_round"], order_type="MARKET",
        product="NRML" if pos["trade_mode"] == "OPTIONS" else "CNC",
        tag="auto_trader",
    )
    if order.get("status") != "ok":
        print(f"[auto_trader] averaging order FAILED {pos['symbol']}: {order.get('message')}")
        return

    new_total_qty = pos["total_qty"] + pos["qty_per_round"]
    new_avg = (cost_basis + added_capital) / new_total_qty
    new_round = pos["rounds"] + 1
    now_iso = datetime.now(IST).isoformat()
    orders = (pos.get("orders") or []) + [{
        "order_id": order["order_id"], "side": "BUY", "qty": pos["qty_per_round"],
        "price": round(cur_price, 2), "round": new_round, "at": now_iso,
    }]
    pnl = (cur_price - new_avg) * new_total_qty
    _update_position(
        pos["id"],
        total_qty=new_total_qty, avg_price=round(new_avg, 2), rounds=new_round,
        current_price=round(cur_price, 2), last_order_at=now_iso, orders=orders,
        pnl=round(pnl, 2),
        pnl_pct=round((pnl / (new_avg * new_total_qty) * 100) if new_avg else 0, 2),
    )
    print(f"[auto_trader] AVERAGED {pos['symbol']} round {new_round} @ {cur_price}, new avg {round(new_avg, 2)}")


def _exit_position(pos: dict, cur_price: float, reason: str) -> Optional[dict]:
    order = zerodha_api.place_order(
        symbol=pos["tradingsymbol"], exchange=pos["exchange"], transaction_type="SELL",
        quantity=pos["total_qty"], order_type="MARKET",
        product="NRML" if pos["trade_mode"] == "OPTIONS" else "CNC",
        tag="auto_trader",
    )
    if order.get("status") != "ok":
        print(f"[auto_trader] exit order FAILED {pos['symbol']}: {order.get('message')}")
        return None

    pnl = (cur_price - pos["avg_price"]) * pos["total_qty"]
    now_iso = datetime.now(IST).isoformat()
    orders = (pos.get("orders") or []) + [{
        "order_id": order["order_id"], "side": "SELL", "qty": pos["total_qty"],
        "price": round(cur_price, 2), "round": pos["rounds"], "at": now_iso,
    }]
    updated = _update_position(
        pos["id"], status="CLOSED", current_price=round(cur_price, 2),
        pnl=round(pnl, 2),
        pnl_pct=round((pnl / (pos["avg_price"] * pos["total_qty"]) * 100) if pos["avg_price"] else 0, 2),
        closed_at=now_iso, exit_reason=reason, orders=orders,
        last_order_at=now_iso,
    )
    print(f"[auto_trader] EXIT {pos['symbol']} ({reason}) @ {cur_price}, P&L {round(pnl,2)}")
    return updated


def _check_exits_and_averaging(cfg: dict):
    open_positions = get_positions(status="OPEN")
    if not open_positions:
        return

    by_exchange: Dict[str, List[str]] = {}
    for p in open_positions:
        by_exchange.setdefault(p["exchange"], []).append(p["tradingsymbol"])

    quotes = {}
    for exch, syms in by_exchange.items():
        try:
            quotes.update(zerodha_api.get_quotes(list(set(syms)), exchange=exch))
        except Exception:
            pass

    for p in open_positions:
        q = quotes.get(p["tradingsymbol"])
        if not q:
            continue
        cur = q["last_price"]
        if not cur:
            continue

        deployed = p["avg_price"] * p["total_qty"]
        pnl = (cur - p["avg_price"]) * p["total_qty"]
        pnl_pct = (pnl / deployed * 100) if deployed else 0

        if _recently_ordered(p):
            _update_position(p["id"], current_price=round(cur, 2), pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 2))
            continue

        # Profit target -> exit, no stop-loss ever
        if pnl_pct >= cfg["profit_target_pct"]:
            _exit_position(p, cur, reason="profit_target")
            continue

        if p.get("paused_averaging") or p["rounds"] >= cfg["max_averaging_rounds"]:
            _update_position(p["id"], current_price=round(cur, 2), pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 2))
            continue

        drop_pct = ((p["avg_price"] - cur) / p["avg_price"] * 100) if p["avg_price"] else 0
        if drop_pct >= cfg["averaging_drop_pct"]:
            _average_down(p, cur, cfg)
        else:
            _update_position(p["id"], current_price=round(cur, 2), pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 2))


# ── Public entry point (call once per Streamlit rerun) ──────────────────────

def evaluate_signals(scan_data: dict):
    """
    Run one full engine tick: check existing positions for averaging/profit
    exit, then look for new entries among BUY signals in `scan_data`
    (the same {nse_symbol: {"signal","spot","buy_count",...}} dict the
    Scanner tab already computes every rerun).
    No-op if market is closed, trading is paused, or Kite isn't connected.
    """
    if not is_market_open():
        return
    cfg = get_config()
    if cfg.get("trade_paused"):
        return
    if not zerodha_api.is_connected():
        return

    with _engine_lock:
        try:
            _check_exits_and_averaging(cfg)
        except Exception as e:
            print(f"[auto_trader] exit/averaging check error: {e}")
        try:
            _check_new_entries(scan_data, cfg)
        except Exception as e:
            print(f"[auto_trader] entry check error: {e}")


# ── Manual dashboard actions ─────────────────────────────────────────────────

def exit_now(position_id: str) -> Optional[dict]:
    with _engine_lock:
        p = next((r for r in get_positions(status="OPEN") if r["id"] == position_id), None)
        if not p:
            return None
        try:
            q = zerodha_api.get_quotes([p["tradingsymbol"]], exchange=p["exchange"])
            cur = q.get(p["tradingsymbol"], {}).get("last_price") or p["current_price"]
        except Exception:
            cur = p["current_price"]
        return _exit_position(p, cur, reason="manual")


def set_averaging_paused(position_id: str, paused: bool = True) -> Optional[dict]:
    with _engine_lock:
        return _update_position(position_id, paused_averaging=paused)
