"""Real-time quotes over WebSocket."""
import asyncio
import concurrent.futures
from typing import List

import yfinance as yf
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.cache import TTLCache
from app.core.config import SYMBOLS
from app.services import zerodha
from app.services.sms import get_watchlist

router = APIRouter(tags=["ticker"])

_cache = TTLCache("ticker")
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=20)

# App index names differ from Kite tradingsymbols
_KITE_INDEX_ALIASES = {
    "NIFTY 50":       "NIFTY 50",
    "BANK NIFTY":     "NIFTY BANK",
    "FIN NIFTY":      "NIFTY FIN SERVICE",
    "MIDCAP SELECT":  "NIFTY MID SELECT",
    "INDIA VIX":      "INDIA VIX",
    "SENSEX":         "",  # BSE, not available via the NSE Kite segment
}


@router.websocket("/ws/ticker")
async def ws_ticker(websocket: WebSocket, symbols: str = Query(default="")):
    await websocket.accept()

    sym_list = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else []

    loop = asyncio.get_event_loop()

    def _get_quotes_sync(syms: List[str]) -> dict:
        if not syms or not zerodha.is_connected():
            return {}

        def _fetch():
            # app names differ from Kite's tradingsymbols: "BANK NIFTY" -> "NIFTY BANK", "HDFC BANK" -> "HDFCBANK"
            alias = {s: (_KITE_INDEX_ALIASES.get(s) or SYMBOLS.get(s, {}).get("nse") or s) for s in syms}
            raw = zerodha.get_quotes(sorted(set(alias.values())))
            return {
                sym: {"ltp": d.get("last_price", 0), "pct": d.get("pct", 0), "change": d.get("change", 0)}
                for sym, kite_sym in alias.items() if (d := raw.get(kite_sym))
            }
        try:
            # shared across every connected client: N tabs = 1 Kite call per 1.5s
            return _cache.get(("ws-quotes", tuple(sorted(syms))), ttl=1.5, compute=_fetch, stale_ttl=6)
        except Exception:
            return {}

    def _get_quotes_yf_fallback(syms: List[str]) -> dict:
        """Fallback: fetch last price from yfinance fast_info for each symbol."""
        result = {}
        for sym in syms:
            try:
                fi = yf.Ticker(f"{sym}.NS").fast_info
                ltp = getattr(fi, "last_price", None) or getattr(fi, "regularMarketPrice", None)
                prev = getattr(fi, "previous_close", None) or getattr(fi, "regularMarketPreviousClose", None)
                if ltp and ltp > 0:
                    change = round(ltp - (prev or ltp), 2) if prev else 0
                    pct = round(change / prev * 100, 2) if prev and prev > 0 else 0
                    result[sym] = {"ltp": round(ltp, 2), "pct": pct, "change": change}
            except Exception:
                pass
        return result

    last_sent: dict = {}

    async def _send_changes(data: dict):
        """Only push symbols whose price moved — keeps the socket quiet when the market is."""
        delta = {s: q for s, q in data.items() if last_sent.get(s) != q}
        if delta:
            last_sent.update(delta)
            await websocket.send_json(delta)

    try:
        # Send initial snapshot
        active_syms = sym_list if sym_list else get_watchlist()
        if active_syms:
            initial = await loop.run_in_executor(
                _executor, _get_quotes_sync, active_syms
            )
            if not initial:
                initial = await loop.run_in_executor(
                    _executor, _get_quotes_yf_fallback, active_syms[:10]
                )
            if initial:
                await _send_changes(initial)

        # Stream updates every 2 seconds
        while True:
            await asyncio.sleep(2)
            current_syms = sym_list if sym_list else get_watchlist()
            if not current_syms:
                continue
            quotes_data = await loop.run_in_executor(
                _executor, _get_quotes_sync, current_syms
            )
            if not quotes_data:
                quotes_data = await loop.run_in_executor(
                    _executor, _get_quotes_yf_fallback, current_syms[:10]
                )
            if quotes_data:
                await _send_changes(quotes_data)

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
