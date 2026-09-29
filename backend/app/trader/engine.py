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

Stop-loss (configurable, default 10%): when a position is down `stop_loss_pct`
vs its average price it either EXITs or adds one more lot (AVERAGE), then exits
once max rounds / margin cap are used up. Set stop_loss_pct = 0 to disable it
and get the original behaviour below.

Original no-stop-loss behaviour (stop_loss_pct = 0): a losing position is never auto-closed.
It only exits on a profit-target hit, an "Exit Now" click, or the user
manually squaring it off in Kite. This means a position CAN sit at an
unbounded loss if price keeps falling past max averaging rounds — the
'Max Margin Per Trade' and 'Max Averaging Rounds' caps are the only ceiling
on how much capital that can consume.
"""
import traceback
import json
import os
import threading
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional

import pytz

from app.services import zerodha
from app.core.config import data_path
from app.services.market_data import is_market_open

IST = pytz.timezone("Asia/Kolkata")

# Absolute paths (see config.data_path): the worker and the API must read/write the SAME files.
CONFIG_FILE = data_path("auto_trader_config.json")
POSITIONS_FILE = data_path("auto_trader_positions.json")

DEDUP_SECONDS = 60  # never fire two orders for the same position within this window
# Intraday only: every order is MIS. No new entries after ENTRY_CUTOFF; anything still open at
# SQUARE_OFF_TIME is sold by the bot (before Zerodha's own ~3:20 PM auto square-off, which charges a fee).
ENTRY_CUTOFF = (15, 0)
SQUARE_OFF_TIME = (15, 15)
EXIT_COOLDOWN_SECONDS = 60  # after an exit, wait before a new entry so released funds show up in Kite

DEFAULT_CONFIG = {
    "id": 1,
    "total_capital": 100000.0,
    "max_margin_pct": 20.0,        # % of total capital allowed per single trade
    "max_active_trades": 2,
    "max_trades_per_day": 3,       # new entries allowed per calendar day (IST); 0 = unlimited
    "profit_target_pct": 10.0,     # % of deployed capital -> auto exit
    "averaging_drop_pct": 5.0,     # price drop % below avg price -> next buy
    "max_averaging_rounds": 3,
    "trade_mode": "OPTIONS",       # OPTIONS | EQUITY
    "trade_paused": False,
    "min_entry_score": 3,
    "stop_loss_pct": 10.0,         # loss % vs avg price that triggers the stop-loss action (0 = disabled)
    "stop_loss_action": "EXIT",    # EXIT = sell everything | AVERAGE = add one more lot (exit once rounds/margin run out)          # min indicators (of 5) agreeing before a watchlist stock is traded
}

# Guards every read-modify-write across a single Streamlit process so two
# concurrent sessions/reruns can't both act on the same signal/position.
_engine_lock = threading.RLock()


# ── Secrets / Supabase (same pattern as jobs/trades.py / services/sms.py) ─────────

def _get_secret(key: str) -> str:
    val = os.environ.get(key, "")
    if val:
        return val
    return ""


_supabase_client = None


def _get_supabase():
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    url = _get_secret("SUPABASE_URL")
    key = _get_secret("SUPABASE_KEY")
    if not url or not key:
        print(f"[auto_trader] Supabase NOT configured (SUPABASE_URL set: {bool(url)}, SUPABASE_KEY set: {bool(key)}) — using local files only")
        return None
    try:
        from supabase import create_client
        _supabase_client = create_client(url, key)
        return _supabase_client
    except Exception as e:
        print(f"[auto_trader] Supabase client creation FAILED ({url}): {e}")
        return None


# ── Activity log (shown in the dashboard's "Activity log" panel) ─────────────

LOG_FILE = data_path("auto_trader_log.jsonl")
_SKIP_REPEAT_SECONDS = 600     # identical SKIP/ERROR lines are only recorded once per 10 min
_last_event: Dict[tuple, float] = {}


def _event(kind: str, symbol: str, message: str):
    """Print + persist one engine event. kind: ENTERED | EXIT | AVERAGED | SKIP | FAILED | ERROR."""
    if kind in ("SKIP", "ERROR"):
        key = (kind, symbol, message)
        now = time.time()
        if now - _last_event.get(key, 0) < _SKIP_REPEAT_SECONDS:
            return
        _last_event[key] = now
    print(f"[auto_trader] {kind} {symbol}: {message}")
    row = {"at": datetime.now(IST).isoformat(), "kind": kind, "symbol": symbol or "", "message": message}
    sb = _get_supabase()
    if sb:
        try:
            sb.table("auto_trader_logs").insert(row).execute()
            return
        except Exception as e:
            print(f"[auto_trader] log insert failed (run the auto_trader_logs SQL?): {e}")
    try:
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:
        pass


def get_logs(limit: int = 200, kinds: Optional[List[str]] = None) -> List[dict]:
    """Newest first."""
    rows: List[dict] = []
    sb = _get_supabase()
    if sb:
        try:
            q = sb.table("auto_trader_logs").select("*").order("id", desc=True).limit(limit)
            if kinds:
                q = q.in_("kind", kinds)
            rows = _clean_rows(q.execute().data)
        except Exception:
            rows = []
    try:
        with open(LOG_FILE) as f:
            for line in f.readlines()[-limit:]:
                try:
                    r = json.loads(line)
                    if not kinds or r.get("kind") in kinds:
                        rows.append(r)
                except Exception:
                    pass
    except Exception:
        pass
    rows.sort(key=lambda r: r.get("at") or "", reverse=True)
    return rows[:limit]


# ── Config persistence ──────────────────────────────────────────────────────

_config_cache: Optional[dict] = None


def get_config(force_reload: bool = False) -> dict:
    global _config_cache
    with _engine_lock:
        if _config_cache is not None and not force_reload:
            return dict(_config_cache)
        cfg = {}
        try:
            with open(CONFIG_FILE) as f:
                cfg.update(json.load(f))
        except Exception:
            pass
        sb = _get_supabase()
        if sb:
            try:
                resp = sb.table("auto_trader_config").select("*").eq("id", 1).execute()
                if resp.data:
                    cfg.update({k: v for k, v in resp.data[0].items() if v is not None})
            except Exception:
                pass
        merged = dict(DEFAULT_CONFIG)
        merged.update({k: v for k, v in cfg.items() if v is not None})
        merged["id"] = 1
        _config_cache = merged
        return dict(merged)


_config_loaded_at = 0.0


def get_config_fresh(max_age: float = 3.0) -> dict:
    """Config no older than `max_age` seconds. The exit loop runs every second, so it must not hit the
    database each time, but a pause/stop-loss change from the dashboard still has to land within a few seconds."""
    global _config_loaded_at
    if time.time() - _config_loaded_at > max_age:
        cfg = get_config(force_reload=True)
        _config_loaded_at = time.time()
        return cfg
    return get_config()


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
                print("[auto_trader] config saved to Supabase")
            except Exception as e:
                print(f"[auto_trader] supabase save config FAILED: {e}")
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass
        global _config_cache
        _config_cache = cfg
        return dict(cfg)


# ── Position persistence ────────────────────────────────────────────────────

def _load_file_positions() -> List[dict]:
    try:
        with open(POSITIONS_FILE) as f:
            return _clean_rows(json.load(f))
    except Exception:
        return []


def _load_all_positions() -> List[dict]:
    """Supabase rows plus any rows that only made it to the local fallback file
    (when a Supabase insert failed) — otherwise the max-active-trades check can't see them."""
    rows: List[dict] = []
    sb = _get_supabase()
    if sb:
        try:
            resp = sb.table("auto_trader_positions").select("*").order("created_at", desc=True).execute()
            rows = _clean_rows(resp.data)
        except Exception as e:
            print(f"[auto_trader] supabase load positions failed: {e}")
    seen = {r.get("id") for r in rows}
    rows += [r for r in _load_file_positions() if r.get("id") not in seen]
    return rows


def _clean_rows(rows) -> List[dict]:
    """Keep only dict rows; warn if the store returned something else (e.g. a dict or strings)."""
    if not rows:
        return []
    if isinstance(rows, dict):
        rows = rows.get("positions") or []
    good = [r for r in rows if isinstance(r, dict)]
    if len(good) != len(rows):
        print(f"[auto_trader] ignoring {len(rows) - len(good)} malformed position row(s), e.g. {rows[0]!r:.120}")
    return good


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
        except Exception as e:
            print(f"[auto_trader] supabase insert position failed, saving locally: {e}")
    rows = _load_file_positions()
    rows.append(pos)
    _save_all_positions_fallback(rows)
    return pos


def _update_position(position_id: str, **fields) -> Optional[dict]:
    sb = _get_supabase()
    if sb:
        try:
            sb.table("auto_trader_positions").update(fields).eq("id", position_id).execute()
            resp = sb.table("auto_trader_positions").select("*").eq("id", position_id).execute()
            if resp.data:
                return resp.data[0]
        except Exception as e:
            print(f"[auto_trader] supabase update position failed: {e}")
    rows = _load_file_positions()
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
    if zerodha.is_connected():
        try:
            reconcile_positions()
        except Exception:
            pass
    open_positions = get_positions(status="OPEN")
    if not open_positions or not zerodha.is_connected():
        return open_positions

    by_exchange: Dict[str, List[str]] = {}
    for p in open_positions:
        by_exchange.setdefault(p["exchange"], []).append(p["tradingsymbol"])

    quotes = {}
    for exch, syms in by_exchange.items():
        try:
            quotes.update(zerodha.get_quotes(list(set(syms)), exchange=exch))
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
    connected = zerodha.is_connected()
    live_cash = _available_cash() if connected else 0
    available = live_cash if live_cash else max(total_capital - deployed, 0)
    # Kite's own figure covers manual trades too; the ledger only knows the bot's.
    live_pnl = _account_pnl() if connected else None

    return {
        "total_capital": total_capital,
        "deployed": round(deployed, 2),
        "available": round(available, 2),
        "available_is_live": bool(live_cash),
        "pnl_today": round(live_pnl if live_pnl is not None else pnl_open + pnl_closed_today, 2),
        "pnl_is_live": live_pnl is not None,
        "open_count": len(open_positions),
        "max_active_trades": cfg["max_active_trades"],
    }


def _hm() -> tuple:
    n = datetime.now(IST)
    return (n.hour, n.minute)


def _product_for(pos: dict) -> str:
    """MIS for today's trades. Positions opened on an earlier day (before intraday-only) keep their old product."""
    created = str(pos.get("created_at") or "")[:10]
    if created and created < datetime.now(IST).date().isoformat():
        return "NRML" if pos.get("trade_mode") == "OPTIONS" else "CNC"
    return "MIS"


def past_square_off_warning_time() -> bool:
    """True after 3:15 PM IST — dashboard should show the no-auto-square-off warning."""
    now = datetime.now(IST)
    return (now.hour, now.minute) >= (15, 15)


# ── Order sizing ─────────────────────────────────────────────────────────────

def _available_cash() -> float:
    try:
        return zerodha.get_available_funds()
    except Exception:
        return 0.0


def _account_pnl() -> Optional[float]:
    try:
        return zerodha.get_account_pnl()
    except Exception:
        return None


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

def _enter_trade(nse_symbol: str, spot: float, cfg: dict, direction: str = "BUY") -> Optional[dict]:
    """direction BUY (bullish) -> buy ATM CE; SELL (bearish) -> buy ATM PE (OPTIONS mode only)."""
    if direction == "SELL" and cfg["trade_mode"] != "OPTIONS":
        return None  # equity CNC can't be shorted
    max_trade_capital = cfg["total_capital"] * cfg["max_margin_pct"] / 100.0
    if max_trade_capital <= 0:
        return None

    # Never size or place an order beyond the real funds in the account.
    available = _available_cash()
    if available <= 0:
        _event("SKIP", nse_symbol, "no available funds (or margin lookup failed)")
        return None
    budget = min(max_trade_capital, available)

    if cfg["trade_mode"] == "OPTIONS":
        want = "CE" if direction == "BUY" else "PE"
        opt = zerodha.pick_atm_option(nse_symbol, spot, want)
        if not opt or not opt.get("ltp"):
            _event("SKIP", nse_symbol, f"no ATM {want} contract/LTP found (spot {spot:.2f})")
            return None
        lot_size = opt["lot_size"]
        lot_cost = opt["ltp"] * lot_size
        lots = int(budget // lot_cost)
        if lots < 1:
            mon = datetime.strptime(opt["expiry"], "%Y-%m-%d").strftime("%b").upper()
            _event("SKIP", nse_symbol, f"{nse_symbol} {mon} {opt['strike']:g}{want} "
                   f"@{opt['ltp']:g}×{lot_size}={lot_cost:.0f} > budget {budget:.0f}")
            return None
        qty = lots * lot_size
        exchange, tradingsymbol, option_type = "NFO", opt["tradingsymbol"], want
        product = "MIS"
        entry_price = opt["ltp"]
        instrument_token = opt["instrument_token"]
    else:
        if spot <= 0:
            return None
        qty = int(budget // spot)
        if qty < 1:
            _event("SKIP", nse_symbol, f"price {spot:.0f} exceeds the budget {budget:.0f}")
            return None
        exchange, tradingsymbol, option_type = "NSE", nse_symbol, None
        product = "MIS"
        entry_price = spot
        instrument_token = zerodha.get_instrument_token(nse_symbol, "NSE")

    if qty * entry_price > available:
        _event("SKIP", nse_symbol, f"{tradingsymbol}: order cost {qty*entry_price:.0f} exceeds available funds {available:.0f}")
        return None

    order = zerodha.place_and_confirm(
        symbol=tradingsymbol, exchange=exchange, transaction_type="BUY",
        quantity=qty, order_type="MARKET", product=product, tag="auto_trader",
    )
    if order.get("status") != "ok":
        _event("FAILED", nse_symbol, f"entry order {tradingsymbol}: {order.get('message')}")
        return None
    qty = int(order.get("filled_qty") or qty)
    entry_price = order.get("avg_price") or entry_price

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
    _event("ENTERED", nse_symbol, f"{tradingsymbol} x{qty} @ {entry_price} (cost {qty * entry_price:.0f}, funds were {available:.0f})")
    return pos


def _check_new_entries(scan_data: dict, cfg: dict):
    """
    scan_data: {nse_symbol: {"signal": "BUY"|"SELL", "spot", "score", ...}} — the
    auto-trade watchlist (top stocks per sector). Bullish picks buy CE, bearish
    picks buy PE. Strongest conviction first.
    """
    if _hm() >= ENTRY_CUTOFF:
        return   # intraday only: no fresh entries near the close
    all_positions = get_positions()
    open_positions = [p for p in all_positions if p.get("status") == "OPEN"]
    if len(open_positions) >= cfg["max_active_trades"]:
        return

    # Funds from a just-closed trade take a moment to reflect in Kite — wait before re-entering.
    for p in all_positions:
        closed = p.get("closed_at")
        if p.get("status") == "CLOSED" and closed:
            try:
                t = datetime.fromisoformat(closed)
                if t.tzinfo is None:
                    t = IST.localize(t)
                if (datetime.now(IST) - t).total_seconds() < EXIT_COOLDOWN_SECONDS:
                    return
            except Exception:
                pass

    slots = cfg["max_active_trades"] - len(open_positions)
    day_limit = int(cfg.get("max_trades_per_day") or 0)
    if day_limit > 0:
        today = datetime.now(IST).date().isoformat()
        entered_today = sum(1 for p in all_positions if str(p.get("created_at") or "")[:10] == today)
        if entered_today >= day_limit:
            return
        slots = min(slots, day_limit - entered_today)
    open_symbols = {p["symbol"] for p in open_positions}
    min_score = cfg.get("min_entry_score", 3)

    candidates = [
        (sym, v) for sym, v in scan_data.items()
        if v.get("signal") in ("BUY", "SELL") and sym not in open_symbols and v.get("spot")
        and (v.get("score") or v.get("buy_count") or 0) >= min_score
        and not (v["signal"] == "SELL" and cfg["trade_mode"] != "OPTIONS")
    ]
    candidates.sort(key=lambda kv: -(kv[1].get("score") or kv[1].get("buy_count") or 0))

    for sym, v in candidates[:slots]:
        try:
            _enter_trade(sym, v["spot"], cfg, direction=v["signal"])
        except Exception as e:
            _event("ERROR", sym, f"entry error: {e}")


# ── Averaging / exits ────────────────────────────────────────────────────────

def _lot_size(pos: dict) -> int:
    """One lot for this position's contract (falls back to the size of a normal round)."""
    if pos.get("trade_mode") == "OPTIONS":
        try:
            for r in zerodha._get_nfo_instruments(pos["symbol"]) or []:
                if r.get("tradingsymbol") == pos["tradingsymbol"]:
                    return int(r.get("lot_size") or pos["qty_per_round"])
        except Exception:
            pass
    return pos["qty_per_round"]


def _average_down(pos: dict, cur_price: float, cfg: dict, qty: Optional[int] = None) -> str:
    """
    Buy `qty` more (default: one normal round). Returns "ok", "blocked"
    (margin cap / cash — nothing was ordered) or "failed" (broker rejected the order).
    """
    qty = qty or pos["qty_per_round"]
    cost_basis = pos["avg_price"] * pos["total_qty"]
    added_capital = cur_price * qty
    max_trade_capital = cfg["total_capital"] * cfg["max_margin_pct"] / 100.0

    if cost_basis + added_capital > max_trade_capital:
        _event("SKIP", pos["symbol"], "averaging skipped: would exceed per-trade margin cap")
        return "blocked"

    available = _available_cash()
    if available < added_capital:
        _event("SKIP", pos["symbol"], "averaging skipped: insufficient available funds")
        return "blocked"

    order = zerodha.place_and_confirm(
        symbol=pos["tradingsymbol"], exchange=pos["exchange"], transaction_type="BUY",
        quantity=qty, order_type="MARKET",
        product=_product_for(pos),
        tag="auto_trader",
    )
    if order.get("status") != "ok":
        _event("FAILED", pos["symbol"], f"averaging order: {order.get('message')}")
        return "failed"
    qty = int(order.get("filled_qty") or qty)
    cur_price = order.get("avg_price") or cur_price
    added_capital = cur_price * qty

    new_total_qty = pos["total_qty"] + qty
    new_avg = (cost_basis + added_capital) / new_total_qty
    new_round = pos["rounds"] + 1
    now_iso = datetime.now(IST).isoformat()
    orders = (pos.get("orders") or []) + [{
        "order_id": order["order_id"], "side": "BUY", "qty": qty,
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
    _event("AVERAGED", pos["symbol"], f"{pos['tradingsymbol']} +{qty} round {new_round} @ {cur_price}, new avg {round(new_avg, 2)}")
    return "ok"


def _exit_position(pos: dict, cur_price: float, reason: str) -> Optional[dict]:
    order = zerodha.place_and_confirm(
        symbol=pos["tradingsymbol"], exchange=pos["exchange"], transaction_type="SELL",
        quantity=pos["total_qty"], order_type="MARKET",
        product=_product_for(pos),
        tag="auto_trader",
    )
    if order.get("status") != "ok":
        _event("FAILED", pos["symbol"], f"exit order ({reason}): {order.get('message')}")
        return None

    sold = int(order.get("filled_qty") or pos["total_qty"])
    if sold < pos["total_qty"]:      # partial fill: keep the remainder open, retry next tick
        _update_position(pos["id"], total_qty=pos["total_qty"] - sold,
                         last_order_at=datetime.now(IST).isoformat())
        _event("EXIT", pos["symbol"], f"PARTIAL: sold {sold}/{pos['total_qty']}, rest stays open")
        return None
    cur_price = order.get("avg_price") or cur_price

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
    _event("EXIT", pos["symbol"], f"{pos['tradingsymbol']} ({reason}) @ {cur_price}, P&L {round(pnl,2)}")
    return updated


_PERSIST_EVERY = 5.0          # seconds between price/P&L writes per position (exits are still checked every tick)
_last_persist: Dict[str, float] = {}


def _persist_price(p: dict, cur: float, pnl: float, pnl_pct: float):
    now = time.time()
    if now - _last_persist.get(p["id"], 0) < _PERSIST_EVERY:
        return
    _last_persist[p["id"]] = now
    _update_position(p["id"], current_price=round(cur, 2), pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 2))


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
            quotes.update(zerodha.get_quotes(list(set(syms)), exchange=exch))
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
            _persist_price(p, cur, pnl, pnl_pct)
            continue

        # Intraday: flat by the square-off time, whatever the P&L
        if _hm() >= SQUARE_OFF_TIME:
            _exit_position(p, cur, reason="intraday_squareoff")
            continue

        # Profit target -> exit, no stop-loss ever
        if pnl_pct >= cfg["profit_target_pct"]:
            _exit_position(p, cur, reason="profit_target")
            continue

        # Stop-loss: at -stop_loss_pct either exit, or add one more lot (then exit once
        # rounds / margin are used up). When enabled it replaces the plain drop-% averaging.
        sl = float(cfg.get("stop_loss_pct") or 0)
        if sl > 0:
            if pnl_pct <= -sl:
                can_average = (
                    cfg.get("stop_loss_action") == "AVERAGE"
                    and not p.get("paused_averaging")
                    and p["rounds"] < cfg["max_averaging_rounds"]
                )
                if can_average:
                    result = _average_down(p, cur, cfg, qty=_lot_size(p))
                    if result in ("ok", "failed"):   # "failed" = retry next tick, don't dump on a broker hiccup
                        continue
                _exit_position(p, cur, reason="stop_loss")
            else:
                _persist_price(p, cur, pnl, pnl_pct)
            continue

        if p.get("paused_averaging") or p["rounds"] >= cfg["max_averaging_rounds"]:
            _persist_price(p, cur, pnl, pnl_pct)
            continue

        drop_pct = ((p["avg_price"] - cur) / p["avg_price"] * 100) if p["avg_price"] else 0
        if drop_pct >= cfg["averaging_drop_pct"]:
            _average_down(p, cur, cfg)
        else:
            _persist_price(p, cur, pnl, pnl_pct)


# ── Public entry point (call once per Streamlit rerun) ──────────────────────

_last_reconcile = 0.0
_last_restore = 0.0
RECONCILE_EVERY = 15.0        # seconds; reconcile calls two Kite endpoints, so not on every 1s tick


def monitor_positions() -> str:
    """
    Fast path, run every ~1s by the worker: profit-target / stop-loss / square-off exits and averaging
    for open positions. Never looks for new entries. Cheap when nothing is open (one position lookup).
    Returns "ran" or the reason it was skipped ("market_closed" | "paused" | "kite_disconnected").
    """
    global _last_reconcile
    if not is_market_open():
        return "market_closed"
    cfg = get_config_fresh()
    if cfg.get("trade_paused"):
        return "paused"
    if not zerodha.is_connected():
        # today's login may have happened in another process (dashboard / API): pick up the saved token
        global _last_restore
        if time.time() - _last_restore >= 10:
            _last_restore = time.time()
            zerodha.restore_saved_token()
        if not zerodha.is_connected():
            return "kite_disconnected"

    with _engine_lock:
        if time.time() - _last_reconcile >= RECONCILE_EVERY:
            _last_reconcile = time.time()
            try:
                reconcile_positions()
            except Exception as e:
                _event("ERROR", "", f"reconcile error: {e}")
        try:
            _check_exits_and_averaging(cfg)
        except Exception as e:
            _event("ERROR", "", f"exit/averaging check error: {e}")
            traceback.print_exc()
    return "ran"


def evaluate_entries(scan_data: dict) -> str:
    """
    Slow path, run every ~30s by the worker: look for new entries among the bullish/bearish picks in
    `scan_data` ({nse_symbol: {"signal","spot","score",...}} — the sector watchlist).
    Returns "ran" or the reason it was skipped ("market_closed" | "paused" | "kite_disconnected").
    """
    if not is_market_open():
        return "market_closed"
    cfg = get_config(force_reload=True)   # pick up dashboard changes made in another process
    if cfg.get("trade_paused"):
        return "paused"
    if not zerodha.is_connected():
        return "kite_disconnected"

    with _engine_lock:
        try:
            _check_new_entries(scan_data, cfg)
        except Exception as e:
            _event("ERROR", "", f"entry check error: {e}")
            traceback.print_exc()
    return "ran"


# ── Worker heartbeat (lets the dashboard show whether the background worker is alive) ──

HEARTBEAT_FILE = data_path("auto_trader_heartbeat.json")


def write_heartbeat(status: str, watchlist_size: int = 0):
    payload = {"at": datetime.now(IST).isoformat(), "status": status, "watchlist": watchlist_size}
    sb = _get_supabase()
    if sb:
        try:
            sb.table("config").upsert({
                "key": "auto_trader_heartbeat", "value": json.dumps(payload),
                "updated_at": payload["at"],
            }).execute()
        except Exception:
            pass
    try:
        with open(HEARTBEAT_FILE, "w") as f:
            json.dump(payload, f)
    except Exception:
        pass


def read_heartbeat() -> Optional[dict]:
    """Returns {"at","status","watchlist","age_seconds"} or None if the worker never reported in."""
    data = None
    sb = _get_supabase()
    if sb:
        try:
            rows = sb.table("config").select("value").eq("key", "auto_trader_heartbeat").execute()
            if rows.data:
                data = json.loads(rows.data[0]["value"])
        except Exception:
            pass
    if data is None:
        try:
            with open(HEARTBEAT_FILE) as f:
                data = json.load(f)
        except Exception:
            return None
    try:
        at = datetime.fromisoformat(data["at"])
        data["age_seconds"] = int((datetime.now(IST) - at).total_seconds())
    except Exception:
        return None
    return data


# ── Sync with Kite (positions closed by hand in the Kite app) ────────────────

SYNC_GRACE_SECONDS = 90   # don't judge a position that was just traded (Kite may lag)


def _manual_exit_price(kite, p: dict) -> Optional[float]:
    """Average fill price of the SELLs you placed in Kite for this position (not the bot's own
    orders, not fills from before it was opened). None if they can't be found."""
    own = {str(o.get("order_id")) for o in p.get("orders") or []}
    try:
        opened = datetime.fromisoformat(p.get("created_at") or "")
        opened = (IST.localize(opened) if opened.tzinfo is None else opened.astimezone(IST)).replace(tzinfo=None)
        fills = [
            t for t in (kite.trades() or [])
            if t.get("tradingsymbol") == p["tradingsymbol"] and t.get("exchange") == p["exchange"]
            and t.get("transaction_type") == "SELL" and str(t.get("order_id")) not in own
            and t.get("fill_timestamp") and t["fill_timestamp"].replace(tzinfo=None) >= opened
        ]
    except Exception:
        return None
    qty = sum(int(t.get("quantity") or 0) for t in fills)
    if not qty:
        return None
    return round(sum(float(t["average_price"]) * int(t["quantity"]) for t in fills) / qty, 2)


def reconcile_positions() -> int:
    """
    Mark OPEN positions CLOSED when Kite no longer holds them (you exited in the Kite app),
    and shrink total_qty if you only sold part. Returns how many were changed.
    Safe: does nothing if Kite can't be reached, so an API failure never closes anything.
    """
    kite = zerodha.get_kite() if zerodha.is_connected() else None
    if not kite:
        return 0
    with _engine_lock:
        open_positions = get_positions(status="OPEN")
        if not open_positions:
            return 0
        try:
            net = (kite.positions() or {}).get("net")
            if not isinstance(net, list):
                return 0
            holdings = []
            if any(p.get("trade_mode") != "OPTIONS" for p in open_positions):
                holdings = kite.holdings() or []
        except Exception as e:
            print(f"[auto_trader] reconcile skipped (Kite unreachable): {e}")
            return 0

        changed = 0
        for p in open_positions:
            if _recently_ordered(p):
                continue
            try:
                created = datetime.fromisoformat(p.get("created_at") or "")
                if created.tzinfo is None:
                    created = IST.localize(created)
                if (datetime.now(IST) - created).total_seconds() < SYNC_GRACE_SECONDS:
                    continue
            except Exception:
                pass
            ts, ex = p["tradingsymbol"], p["exchange"]
            rows = [r for r in net if r.get("tradingsymbol") == ts and r.get("exchange") == ex]
            qty = sum(int(r.get("quantity") or 0) for r in rows)
            if p.get("trade_mode") != "OPTIONS":
                qty += sum(int(h.get("quantity") or 0) + int(h.get("t1_quantity") or 0)
                           for h in holdings if h.get("tradingsymbol") == ts)
            if qty >= p["total_qty"]:
                continue
            now_iso = datetime.now(IST).isoformat()
            if qty > 0:      # sold part of it in Kite
                _update_position(p["id"], total_qty=qty, last_order_at=now_iso)
                _event("EXIT", p["symbol"], f"{ts}: you sold part in Kite, qty {p['total_qty']} -> {qty}")
                changed += 1
                continue
            # Not the Kite position row's pnl: that row sums every trade in this contract today.
            exit_price = _manual_exit_price(kite, p)
            if exit_price:
                pnl = (exit_price - p["avg_price"]) * p["total_qty"]
            else:
                exit_price, pnl = p.get("current_price"), float(p.get("pnl") or 0)
            deployed = p["avg_price"] * p["total_qty"]
            _update_position(
                p["id"], status="CLOSED", pnl=round(pnl, 2), current_price=exit_price,
                pnl_pct=round(pnl / deployed * 100, 2) if deployed else 0,
                closed_at=now_iso, exit_reason="manual_exit", last_order_at=now_iso,
            )
            _event("EXIT", p["symbol"], f"{ts}: no longer held in Kite (closed manually) — marked CLOSED, P&L {pnl:.2f}")
            changed += 1
        return changed


# ── Manual dashboard actions ─────────────────────────────────────────────────

def exit_now(position_id: str) -> Optional[dict]:
    with _engine_lock:
        p = next((r for r in get_positions(status="OPEN") if r["id"] == position_id), None)
        if not p:
            return None
        try:
            q = zerodha.get_quotes([p["tradingsymbol"]], exchange=p["exchange"])
            cur = q.get(p["tradingsymbol"], {}).get("last_price") or p["current_price"]
        except Exception:
            cur = p["current_price"]
        return _exit_position(p, cur, reason="manual")


def set_averaging_paused(position_id: str, paused: bool = True) -> Optional[dict]:
    with _engine_lock:
        return _update_position(position_id, paused_averaging=paused)
