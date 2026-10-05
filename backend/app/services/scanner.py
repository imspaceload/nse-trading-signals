"""
Signal scoring for the scanner / sector-picks endpoints.
Scores each stock 0-5 from RSI, MACD, Supertrend, VWAP and a volume spike.
"""
import concurrent.futures
from typing import List, Optional

import pandas as pd
import yfinance as yf

from app.services import zerodha
from app.services.indicators import compute_macd, compute_rsi, compute_supertrend, compute_vwap, session_stats
from app.services.sector_watchlist import SECTOR_STOCKS

SECTOR_UNIVERSE = tuple(sorted({s for stocks in SECTOR_STOCKS.values() for s in stocks}))

# ── Timeframe map ─────────────────────────────────────────────────────────
TF_YF_MAP = {
    "1m":  ("1d",  "1m"),
    "3m":  ("1d",  "2m"),
    "5m":  ("1d",  "5m"),
    "15m": ("5d",  "15m"),
    "1h":  ("5d",  "60m"),
    "1D":  ("1mo", "1d"),
}


def fetch_ohlcv_bulk_yf(symbols: List[str], timeframe: str) -> dict:
    """Bulk yfinance download for a list of NSE symbols."""
    period, interval = TF_YF_MAP.get(timeframe, ("5d", "15m"))
    tickers = " ".join(f"{s}.NS" for s in symbols)
    try:
        dl = yf.download(tickers, period=period, interval=interval,
                         group_by="ticker", threads=True, progress=False, auto_adjust=True)
        result = {}
        for s in symbols:
            try:
                key = f"{s}.NS"
                if key in dl.columns.get_level_values(0):
                    df = dl[key].dropna()
                    if not df.empty:
                        result[s] = df
            except Exception:
                pass
        return result
    except Exception:
        return {}


def score_one(sym: str, df: pd.DataFrame) -> Optional[dict]:
    """Compute 5-point signal score for a single symbol (RSI+MACD+ST+VWAP+Vol)."""
    if df is None or df.empty or len(df) < 20:
        return None
    try:
        spot = float(df["Close"].iloc[-1])
        rsi_d  = compute_rsi(df)
        macd_d = compute_macd(df)
        st_d   = compute_supertrend(df)
        vwap_d = compute_vwap(df)

        buy_pts = sell_pts = 0
        rsi_sig  = (rsi_d.get("signal")  or "NEUTRAL") if rsi_d  else "NEUTRAL"
        macd_sig = (macd_d.get("signal") or "NEUTRAL") if macd_d else "NEUTRAL"
        vwap_sig = (vwap_d.get("signal") or "NEUTRAL") if vwap_d else "NEUTRAL"

        if rsi_sig  == "BUY":   buy_pts  += 1
        elif rsi_sig  == "SELL": sell_pts += 1
        if macd_sig == "BUY":   buy_pts  += 1
        elif macd_sig == "SELL": sell_pts += 1
        if st_d:
            if st_d.get("direction") == 1: buy_pts  += 1
            else:                           sell_pts += 1
        if vwap_sig == "BUY":   buy_pts  += 1
        elif vwap_sig == "SELL": sell_pts += 1

        try:
            avg_vol   = float(df["Volume"].iloc[:-1].tail(20).mean())
            cur_vol   = float(df["Volume"].iloc[-1])
            vol_spike = avg_vol > 0 and cur_vol > avg_vol * 1.5
        except Exception:
            vol_spike = False

        if vol_spike:
            if buy_pts > sell_pts:   buy_pts  += 1
            elif sell_pts > buy_pts: sell_pts += 1

        max_score = max(buy_pts, sell_pts)
        direction = "BUY" if buy_pts > sell_pts else ("SELL" if sell_pts > buy_pts else "NEUTRAL")

        day_pct = session_stats(df)["day_pct"]

        rsi_val = round(float(rsi_d.get("value") or 50), 1) if rsi_d else 50.0
        return {
            "symbol":     sym,
            "spot":       round(spot, 2),
            "buy_pts":    buy_pts,
            "sell_pts":   sell_pts,
            "score":      max_score,
            "direction":  direction,
            "rsi":        rsi_val,
            "macd":       macd_sig,
            "supertrend": "BULL" if (st_d and st_d.get("direction") == 1) else "BEAR",
            "vwap":       vwap_sig,
            "vol_spike":  vol_spike,
            "day_pct":    day_pct,
        }
    except Exception:
        return None


def run_scanner(symbols: tuple, timeframe: str, use_kite: bool) -> List[dict]:
    """Run signal scoring on a universe of symbols."""
    if use_kite and zerodha.is_connected():
        ohlcv_map = zerodha.get_historical_data_bulk(list(symbols), timeframe, max_workers=5)
    else:
        ohlcv_map = fetch_ohlcv_bulk_yf(list(symbols), timeframe)

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        futs = {ex.submit(score_one, sym, ohlcv_map.get(sym)): sym for sym in symbols}
        try:
            for fut in concurrent.futures.as_completed(futs, timeout=60):
                try:
                    r = fut.result()
                    if r:
                        results.append(r)
                except Exception:
                    pass
        except concurrent.futures.TimeoutError:
            pass

    results.sort(key=lambda x: (x["score"], x["direction"] == "BUY"), reverse=True)
    return results
