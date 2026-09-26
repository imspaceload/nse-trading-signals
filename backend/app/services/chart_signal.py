"""
Signal box + pivot lines for the dashboard chart.

The direction/score is computed exactly the way the auto-trader worker sees a stock: 15m candles over
the same 5-day window, scored by scanner.score_one (RSI + MACD + Supertrend + VWAP + volume spike).
Pivots / targets / stop-losses are the classic floor pivots from the previous session — they are
chart guides only; the worker's entries and exits don't use them.
"""
from typing import List, Optional

import pandas as pd

from app.services import zerodha
from app.services.market_data import _resolve_chart_symbol
from app.services.scanner import SECTOR_UNIVERSE, score_one
from app.services.sector_watchlist import SECTOR_STOCKS

BOT_TIMEFRAME = "15m"   # keep in sync with WATCHLIST_TIMEFRAME in app/trader/worker.py

_INDEX_STRIKE_STEP = {"NIFTY 50": 50, "BANK NIFTY": 100, "FIN NIFTY": 50, "MIDCAP SELECT": 25, "SENSEX": 100}
_NO_OPTIONS_YF = ("CL=", "NG=", "GC=", "SI=", "^BSESN")   # commodities / BSE: no NSE option chain


def _bot_frame(name: str) -> tuple:
    """(source, df) with the same candles the worker scores: Kite 15m x 5 days, else yfinance 5d/15m."""
    kite_sym, yf_sym = _resolve_chart_symbol(name)
    if kite_sym and zerodha.is_connected():
        df = zerodha.get_historical_data(kite_sym, BOT_TIMEFRAME)
        if not df.empty:
            return "kite", df
    import yfinance as yf
    return "yahoo", yf.Ticker(yf_sym).history(period="5d", interval="15m")


def compute_pivots(df: pd.DataFrame) -> dict:
    """Floor pivots from the previous session's H/L/C (fixed for the whole day)."""
    dates = df.index.date
    earlier = dates[dates < dates[-1]]
    day = df[dates == earlier.max()] if len(earlier) else df   # only one session loaded: use it
    h, l, c = float(day["High"].max()), float(day["Low"].min()), float(day["Close"].iloc[-1])
    pp, rng = (h + l + c) / 3, h - l
    return {
        "PP": round(pp, 2),
        "R1": round(2 * pp - l, 2), "R2": round(pp + rng, 2),
        "S1": round(2 * pp - h, 2), "S2": round(pp - rng, 2),
    }


def option_strike(price: float, name: str, listed: List[float]) -> float:
    """Nearest listed strike (what the worker would buy); without Kite, NSE's usual strike intervals."""
    if price <= 0:
        return 0
    if listed:
        return min(listed, key=lambda k: abs(k - price))
    step = _INDEX_STRIKE_STEP.get(name) or (
        1 if price < 25 else 2.5 if price < 50 else 5 if price < 250 else 10 if price < 1000 else 50 if price < 5000 else 100
    )
    return round(price / step) * step


def _levels(direction: str, pv: dict) -> dict:
    """Targets / stop-losses as the old Streamlit signal box showed them."""
    if direction == "BUY":
        t1, t2, sl1, sl2 = pv["R1"], pv["R2"], pv["PP"], pv["S1"]
    elif direction == "SELL":
        t1, t2, sl1, sl2 = pv["S1"], pv["S2"], pv["PP"], pv["R1"]
    else:
        t1, t2, sl1, sl2 = pv["R1"], pv["S1"], pv["PP"], None
    return {"T1": t1, "T2": t2, "AVG": round((t1 + t2) / 2, 2), "SL1": sl1, "SL2": sl2}


def _sector_of(nse_sym: str) -> Optional[str]:
    return next((s for s, syms in SECTOR_STOCKS.items() if nse_sym in syms), None)


def get_chart_signal(name: str, min_score: int) -> Optional[dict]:
    source, df = _bot_frame(name)
    if df is None or df.empty:
        return None
    scored = score_one(name, df)
    if not scored:
        return None

    kite_sym, yf_sym = _resolve_chart_symbol(name)
    pivots = compute_pivots(df)
    direction = scored["direction"]
    has_options = bool(kite_sym) and not yf_sym.startswith(_NO_OPTIONS_YF)
    listed = zerodha.get_option_strikes(kite_sym) if has_options and zerodha.is_connected() else []
    today = df[df.index.date == df.index.date[-1]]

    return {
        "symbol": name,
        "timeframe": BOT_TIMEFRAME,
        "source": source,
        **{k: scored[k] for k in ("spot", "direction", "score", "buy_pts", "sell_pts", "rsi", "macd", "supertrend", "vwap", "vol_spike")},
        "pivots": pivots,
        "levels": _levels(direction, pivots),
        # What to trade: ATM strike for a BUY/SELL signal; for NEUTRAL, the strikes at the R1 / S1 breakout triggers.
        "option": {
            "underlying": kite_sym,
            "atm": option_strike(scored["spot"], name, listed),
            "ce_trigger": pivots["R1"], "ce_strike": option_strike(pivots["R1"], name, listed),
            "pe_trigger": pivots["S1"], "pe_strike": option_strike(pivots["S1"], name, listed),
        } if has_options else None,
        "session": {
            "open": round(float(today["Open"].iloc[0]), 2),
            "high": round(float(today["High"].max()), 2),
            "low": round(float(today["Low"].min()), 2),
        },
        "auto_trader": {
            "scanned": kite_sym in SECTOR_UNIVERSE,
            "sector": _sector_of(kite_sym),
            "min_score": min_score,
        },
    }
