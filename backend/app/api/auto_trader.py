"""
Auto Trader REST API for the Next.js dashboard.

This process only DISPLAYS and CONFIGURES the trader. Orders are placed by the separate
always-on worker (auto_trader_worker.py) — the only order-placing call exposed here is
"exit now" for a single position.

Note: uvicorn runs with several workers, each with its own module state, so every read goes to
the shared store (Supabase / files) with force_reload instead of trusting an in-process cache.
"""
from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.trader import engine
from app.services import zerodha
from app.services.market_data import is_market_open
from app.services.sector_watchlist import build_watchlist

from app.core.cache import TTLCache

router = APIRouter(prefix="/api/auto-trader", tags=["auto-trader"])

_cache = TTLCache("auto-trader")
_KINDS = {"ENTERED", "EXIT", "AVERAGED", "SKIP", "FAILED", "ERROR"}


# ── Models ──────────────────────────────────────────────────────────────────

class ConfigUpdate(BaseModel):
    total_capital: Optional[float] = Field(None, ge=100, le=1e9)
    max_margin_pct: Optional[float] = Field(None, gt=0, le=100)
    max_active_trades: Optional[int] = Field(None, ge=1, le=10)
    max_trades_per_day: Optional[int] = Field(None, ge=0, le=50)
    profit_target_pct: Optional[float] = Field(None, gt=0, le=100)
    averaging_drop_pct: Optional[float] = Field(None, gt=0, le=50)
    max_averaging_rounds: Optional[int] = Field(None, ge=0, le=10)
    trade_mode: Optional[Literal["OPTIONS", "EQUITY"]] = None
    trade_paused: Optional[bool] = None
    min_entry_score: Optional[int] = Field(None, ge=1, le=5)
    stop_loss_pct: Optional[float] = Field(None, ge=0, le=90)
    stop_loss_action: Optional[Literal["EXIT", "AVERAGE"]] = None
    lots_per_trade: Optional[int] = Field(None, ge=0, le=100)
    product: Optional[Literal["NRML", "MIS"]] = None
    square_off_eod: Optional[bool] = None
    max_vwap_distance_pct: Optional[float] = Field(None, ge=0, le=20)
    max_day_move_pct: Optional[float] = Field(None, ge=0, le=20)


class PauseBody(BaseModel):
    paused: bool


# ── Helpers ─────────────────────────────────────────────────────────────────

def _same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(float(a) - float(b)) < 1e-6
    return a == b


def _hhmm(t: tuple) -> str:
    return f"{t[0]:02d}:{t[1]:02d}"


def _build_state() -> dict:
    cfg = engine.get_config(force_reload=True)
    connected = zerodha.is_connected() if zerodha.is_configured() else False

    open_positions = engine.refresh_open_position_prices() if connected else engine.get_positions(status="OPEN")
    all_positions = engine.get_positions()
    today = datetime.now(engine.IST).date().isoformat()
    trades_today = sum(1 for p in all_positions if str(p.get("created_at") or "")[:10] == today)
    closed = sorted(
        [p for p in all_positions if p.get("status") == "CLOSED"],
        key=lambda p: p.get("closed_at") or "",
        reverse=True,
    )[:50]

    hb = engine.read_heartbeat()
    market_open = is_market_open()
    worker_alive = bool(hb) and hb.get("age_seconds", 10**9) < 120
    warnings: List[str] = []
    if not connected:
        warnings.append("Zerodha is not connected — the trader cannot place or exit orders. Log in to Kite.")
    if market_open and not worker_alive:
        warnings.append("The auto-trader worker is not reporting in — nothing will be traded or exited.")
    if cfg.get("trade_paused"):
        warnings.append("Trading is paused — no entries, averaging or exits will happen.")
    if not cfg.get("stop_loss_pct"):
        warnings.append("Stop-loss is OFF — a losing position is never closed automatically.")

    return {
        "config": cfg,
        "summary": engine.get_dashboard_summary(),
        "positions": open_positions,
        "closed": closed,
        "worker": {
            "alive": worker_alive,
            "status": (hb or {}).get("status"),
            "age_seconds": (hb or {}).get("age_seconds"),
            "watchlist": (hb or {}).get("watchlist"),
        },
        "market_open": market_open,
        "kite_connected": connected,
        "trades_today": trades_today,
        "rules": {
            "entry_cutoff": _hhmm(engine.ENTRY_CUTOFF),
            "square_off": _hhmm(engine.SQUARE_OFF_TIME),
            "product": "MIS" if str(cfg.get("product")).upper() == "MIS" else
                       ("NRML" if cfg.get("trade_mode") == "OPTIONS" else "CNC"),
            "exit_cooldown_seconds": engine.EXIT_COOLDOWN_SECONDS,
        },
        "warnings": warnings,
    }


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/state")
def get_state():
    """Everything the Auto Trader tab needs in one request (cached for a few seconds)."""
    try:
        return _cache.get("state", ttl=4, compute=_build_state, stale_ttl=30)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not load auto-trader state: {e}")


@router.put("/config")
def update_config(body: ConfigUpdate):
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status_code=400, detail="No fields to update")
    engine.set_config(**changes)

    # Verify it reached the shared store — the worker is a different process and reads from there.
    saved = engine.get_config(force_reload=True)
    wrong = [k for k, v in changes.items() if not _same(saved.get(k), v)]
    _cache.invalidate("state")
    if wrong:
        raise HTTPException(
            status_code=502,
            detail=("Saved locally but NOT stored in Supabase for: " + ", ".join(wrong) +
                    ". The worker will not see this change — check the auto_trader_config table columns "
                    "(run supabase_auto_trader_tables.sql) and SUPABASE_URL/KEY."),
        )
    return saved


@router.post("/pause")
def set_paused(body: PauseBody):
    return update_config(ConfigUpdate(trade_paused=body.paused))


@router.post("/positions/{position_id}/exit")
def exit_position(position_id: str):
    if not zerodha.is_connected():
        raise HTTPException(status_code=503, detail="Zerodha is not connected")
    result = engine.exit_now(position_id)
    _cache.invalidate("state")
    if not result:
        raise HTTPException(
            status_code=409,
            detail="Exit did not complete — the position may already be closed, or the order was rejected. See the Auto Trade Log.",
        )
    return {"ok": True, "position": result}


@router.post("/positions/{position_id}/averaging")
def set_averaging(position_id: str, body: PauseBody):
    result = engine.set_averaging_paused(position_id, body.paused)
    _cache.invalidate("state")
    if not result:
        raise HTTPException(status_code=404, detail="Position not found")
    return {"ok": True, "position": result}


@router.get("/logs")
def get_logs(
    limit: int = Query(200, ge=1, le=500),
    kinds: Optional[str] = Query(None, description="Comma-separated: ENTERED,EXIT,AVERAGED,SKIP,FAILED,ERROR"),
):
    wanted = None
    if kinds:
        wanted = [k.strip().upper() for k in kinds.split(",") if k.strip()]
        bad = [k for k in wanted if k not in _KINDS]
        if bad:
            raise HTTPException(status_code=400, detail=f"Unknown kind(s): {', '.join(bad)}")
    try:
        return _cache.get(("logs", limit, tuple(wanted or ())), ttl=2,
                          compute=lambda: engine.get_logs(limit=limit, kinds=wanted))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not load logs: {e}")


def _build_watch() -> List[dict]:
    cfg = engine.get_config(force_reload=True)
    min_score = int(cfg.get("min_entry_score") or 3)
    picks = build_watchlist("15m", use_kite=zerodha.is_connected())
    rows = []
    for sym, v in picks.items():
        late = engine.entry_block_reason(v["signal"], v, cfg)
        rows.append({
            "symbol": sym,
            "signal": v["signal"],
            "side": "CE" if v["signal"] == "BUY" else "PE",
            "spot": v["spot"],
            "score": v["score"],
            "sector": v["sector"],
            "rsi": v["rsi"],
            "day_pct": v["day_pct"],
            "vwap_dist_pct": v.get("vwap_dist_pct"),
            "eligible": v["score"] >= min_score and not late,
            "blocked": late,
        })
    rows.sort(key=lambda r: (-r["score"], r["symbol"]))
    return rows


@router.get("/watchlist")
def get_watchlist_rows():
    """The stocks the worker may trade (top 4 per sector, bullish/bearish only)."""
    ttl = 60 if is_market_open() else 600
    try:
        return _cache.get("watch", ttl=ttl, compute=_build_watch, stale_ttl=ttl * 10)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not build the watchlist: {e}")
