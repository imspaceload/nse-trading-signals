#!/usr/bin/env python3
"""
Always-on Auto Trader worker.

Runs the trading engine as its own process — no browser tab, no Streamlit.
Two loops run during market hours:
  * FAST (every EXIT_TICK_SECONDS, default 1s) — checks open positions: profit-target,
    stop-loss and 3:15 PM square-off exits, averaging down. This is the risk side, so it
    never waits on anything slow.
  * SLOW (every ENTRY_TICK_SECONDS, default 30s, in a background thread) — re-loads today's
    Kite token, builds the sector watchlist (top 4 per sector, bullish/bearish; takes several
    seconds) and looks for new entries.

Run it on a machine that stays on (VPS / Railway worker), not a laptop that sleeps:

    cd backend && python -m app.trader.worker

Only ONE worker may run at a time (a lock file enforces this).
You still log in to Zerodha once per trading day (tokens expire daily).
"""
import fcntl
import os
import signal
import sys
import threading
import time
import traceback
from datetime import datetime

import pytz

from app.core import config
from app.services import zerodha
from app.trader import engine
from app.services.market_data import is_market_open
from app.services.sector_watchlist import build_watchlist

IST = pytz.timezone("Asia/Kolkata")
EXIT_TICK_SECONDS = float(os.environ.get("AUTO_TRADER_EXIT_TICK_SECONDS", "1"))
ENTRY_TICK_SECONDS = float(os.environ.get("AUTO_TRADER_TICK_SECONDS", "30"))
IDLE_SECONDS = 60          # sleep between checks while the market is closed
HEARTBEAT_SECONDS = 10
WATCHLIST_TIMEFRAME = "15m"
LOCK_FILE = config.data_path(".auto_trader_worker.lock")

_running = True
_entry_status = "starting"      # last result of the slow loop, reported in the heartbeat
_watchlist_size = 0


def log(msg: str):
    print(f"[worker {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _stop(signum, _frame):
    global _running
    log(f"signal {signum} received — shutting down")
    _running = False


def _acquire_lock():
    """Refuse to start if another worker is running (double trading would place duplicate orders)."""
    fh = open(LOCK_FILE, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("another auto_trader_worker is already running — exiting")
        sys.exit(1)
    fh.write(str(os.getpid()))
    fh.flush()
    return fh  # keep referenced so the lock lives as long as the process


def _ensure_kite() -> bool:
    if zerodha.is_connected():
        return True
    return zerodha.restore_saved_token() and zerodha.is_connected()


def _sleep(seconds: float):
    """Sleep in short steps so a stop signal is honoured promptly."""
    end = time.time() + seconds
    while _running and time.time() < end:
        time.sleep(min(0.25, max(0.0, end - time.time())))


def entry_tick() -> str:
    global _watchlist_size
    if not is_market_open():
        return "market_closed"
    if not _ensure_kite():
        return "kite_disconnected (log in to Zerodha to resume trading)"
    watchlist = build_watchlist(WATCHLIST_TIMEFRAME, use_kite=True)   # slow: several seconds
    _watchlist_size = len(watchlist)
    result = engine.evaluate_entries(watchlist)
    return f"{result} — watchlist {len(watchlist)} stocks"


def entry_loop():
    """Slow loop (own thread): watchlist + new entries. A hang or error here can never delay exits."""
    global _entry_status
    last = None
    while _running:
        started = time.time()
        try:
            status = entry_tick()
        except Exception:
            status = "error"
            log("entry tick failed:\n" + traceback.format_exc())
        _entry_status = status
        if status != last:
            log(f"entries: {status}")
            last = status
        _sleep((ENTRY_TICK_SECONDS if is_market_open() else IDLE_SECONDS) - (time.time() - started))


def main():
    lock = _acquire_lock()  # noqa: F841
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    log(f"started: exits checked every {EXIT_TICK_SECONDS:g}s, entries every {ENTRY_TICK_SECONDS:g}s (pid {os.getpid()})")

    threading.Thread(target=entry_loop, name="entries", daemon=True).start()

    last_status = None
    last_beat = 0.0
    while _running:
        started = time.time()
        try:
            status = engine.monitor_positions()
        except Exception:
            status = "error"
            log("exit tick failed:\n" + traceback.format_exc())
        if status != last_status:      # log state changes, not every tick
            log(f"exits: {status}")
            last_status = status

        if time.time() - last_beat >= HEARTBEAT_SECONDS:
            last_beat = time.time()
            try:
                engine.write_heartbeat(status if status != "ran" else _entry_status.split(" —")[0], watchlist_size=_watchlist_size)
            except Exception:
                pass

        _sleep((EXIT_TICK_SECONDS if is_market_open() else IDLE_SECONDS) - (time.time() - started))

    log("stopped")


if __name__ == "__main__":
    main()
