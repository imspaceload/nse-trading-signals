"""
Sector watchlist logic shared by the Streamlit app and the always-on
auto-trader worker. No Streamlit imports — safe to run headless.
"""
import concurrent.futures

import pandas as pd

from app.services import zerodha
from app.services.indicators import compute_rsi, compute_macd, compute_supertrend, compute_vwap, session_stats

# NSE F&O stocks grouped by sector (trading symbols)
SECTOR_STOCKS = {
    "Banking 🏦":          ["HDFCBANK","ICICIBANK","SBIN","KOTAKBANK","AXISBANK","INDUSINDBK","BANKBARODA","PNB","CANBK","FEDERALBNK","IDFCFIRSTB","BANDHANBNK"],
    "IT / Tech 💻":        ["TCS","INFY","WIPRO","HCLTECH","TECHM","LTIM","MPHASIS","PERSISTENT","COFORGE","OFSS"],
    "Auto 🚗":             ["TATAMOTORS","MARUTI","M&M","BAJAJ-AUTO","HEROMOTOCO","EICHERMOT","TVSMOTOR","ASHOKLEY","MOTHERSON","BALKRISIND"],
    "Pharma 💊":           ["SUNPHARMA","DRREDDY","CIPLA","DIVISLAB","AUROPHARMA","TORNTPHARM","LUPIN","ALKEM","BIOCON","IPCALAB"],
    "FMCG 🛒":             ["HINDUNILVR","ITC","NESTLEIND","BRITANNIA","MARICO","DABUR","GODREJCP","COLPAL","TATACONSUM","EMAMILTD"],
    "Metal & Mining ⛏":   ["TATASTEEL","HINDALCO","JSWSTEEL","SAIL","VEDL","NMDC","NATIONALUM","HINDCOPPER","APLAPOLLO"],
    "Energy & Oil ⚡":     ["RELIANCE","ONGC","BPCL","IOC","GAIL","PETRONET","MGL","IGL","TATAPOWER","ADANIGREEN"],
    "Infrastructure 🏗":   ["LT","ULTRACEMCO","GRASIM","SHREECEM","ADANIPORTS","RVNL","IRFC","PFC","RECLTD","NTPC"],
    "Telecom 📡":          ["BHARTIARTL","IDEA","INDUSTOWER"],
    "Consumer & Retail 🛍":["ZOMATO","DMART","TRENT","JUBLFOOD","DEVYANI","SAPPHIRE","NYKAA","INDHOTEL","EIHOTEL","LEMONTRE"],
    "Financial Services 📈":["BAJFINANCE","BAJAJFINSV","HDFCAMC","MUTHOOTFIN","CHOLAFIN","SBICARD","MANAPPURAM","IIFL","M&MFIN"],
}
# Flat deduplicated list of all stocks across every sector (used by Scanner)
SECTOR_UNIVERSE = tuple(sorted({s for stocks in SECTOR_STOCKS.values() for s in stocks}))



def compute_sector_signals(nse_symbols_tuple: tuple, timeframe: str = "15m", use_kite: bool = False) -> dict:
    """
    Score each stock in a sector 0-5 for BUY/SELL conviction using
    RSI + MACD + Supertrend + VWAP + Volume spike.
    Uses Kite historical data when use_kite=True, yfinance otherwise.
    """
    _tf_map = {"5m":("1d","5m"), "15m":("5d","15m"), "1h":("5d","60m"), "1D":("1mo","1d")}
    period, interval = _tf_map.get(timeframe, ("5d","15m"))

    if use_kite and zerodha.is_connected():
        ohlcv_map = zerodha.get_historical_data_bulk(list(nse_symbols_tuple), timeframe, max_workers=5)
    else:
        # yfinance bulk fallback when Kite is offline
        import yfinance as yf
        _tickers = " ".join(f"{s}.NS" for s in nse_symbols_tuple)
        try:
            _dl = yf.download(_tickers, period=period, interval=interval,
                              group_by="ticker", threads=True, progress=False, auto_adjust=True)
            ohlcv_map = {}
            for _s in nse_symbols_tuple:
                try:
                    _df = _dl[f"{_s}.NS"].dropna() if f"{_s}.NS" in _dl.columns.get_level_values(0) else pd.DataFrame()
                    if not _df.empty:
                        ohlcv_map[_s] = _df
                except Exception:
                    pass
        except Exception:
            ohlcv_map = {}

    def _one(nse_sym):
        try:
            df = ohlcv_map.get(nse_sym)
            if df is None or df.empty or len(df) < 20:
                return nse_sym, None
            spot = float(df["Close"].iloc[-1])
            rsi_d  = compute_rsi(df)
            macd_d = compute_macd(df)
            st_d   = compute_supertrend(df)
            vwap_d = compute_vwap(df)

            buy_pts = sell_pts = 0
            rsi_sig  = (rsi_d.get("signal")  or "NEUTRAL") if rsi_d  else "NEUTRAL"
            macd_sig = (macd_d.get("signal") or "NEUTRAL") if macd_d else "NEUTRAL"
            vwap_sig = (vwap_d.get("signal") or "NEUTRAL") if vwap_d else "NEUTRAL"
            if rsi_sig  == "BUY":  buy_pts  += 1
            elif rsi_sig  == "SELL": sell_pts += 1
            if macd_sig == "BUY":  buy_pts  += 1
            elif macd_sig == "SELL": sell_pts += 1
            if st_d:
                if st_d.get("direction") == 1: buy_pts  += 1
                else:                           sell_pts += 1
            if vwap_sig == "BUY":  buy_pts  += 1
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
            sess = session_stats(df)
            rsi_val = round(float(rsi_d.get("value") or 50), 1) if rsi_d else 50.0
            return nse_sym, {
                "spot": round(spot, 2),
                "buy_pts": buy_pts, "sell_pts": sell_pts,
                "score": max_score, "direction": direction,
                "rsi": rsi_val, "macd": macd_sig,
                "supertrend": "BULL" if (st_d and st_d.get("direction") == 1) else "BEAR",
                "vwap": vwap_sig, "vol_spike": vol_spike,
                "day_pct": sess["day_pct"], "vwap_dist_pct": sess["vwap_dist_pct"],
            }
        except Exception:
            return nse_sym, None

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(_one, s): s for s in nse_symbols_tuple}
        try:
            for fut in concurrent.futures.as_completed(futs, timeout=50):
                try:
                    s, v = fut.result()
                    if v: results[s] = v
                except Exception:
                    pass
        except concurrent.futures.TimeoutError:
            pass
    return results


def build_watchlist(timeframe: str = "15m", use_kite: bool = False, per_sector: int = 4,
                    signals: dict = None) -> dict:
    """
    Top `per_sector` stocks of every sector (11 sectors x 4 = ~44), keeping only
    clear BULLISH (BUY) or BEARISH (SELL) picks.
    Returns {nse_symbol: {"signal","spot","score","sector","rsi","day_pct","vwap_dist_pct"}}.
    Pass `signals` to reuse an already-computed compute_sector_signals() result.
    """
    data = signals if signals is not None else compute_sector_signals(SECTOR_UNIVERSE, timeframe, use_kite=use_kite)
    dir_order = {"BUY": 0, "SELL": 1, "NEUTRAL": 2}
    picks: dict = {}
    for sector, syms in SECTOR_STOCKS.items():
        ranked = sorted(
            ((s, data[s]) for s in syms if s in data),
            key=lambda x: (-x[1]["score"], dir_order.get(x[1]["direction"], 2)),
        )[:per_sector]
        for sym, v in ranked:
            if v["direction"] in ("BUY", "SELL") and sym not in picks:
                picks[sym] = {
                    "signal": v["direction"], "spot": v["spot"], "score": v["score"],
                    "sector": sector, "rsi": v["rsi"], "day_pct": v["day_pct"],
                    "vwap_dist_pct": v["vwap_dist_pct"],
                }
    return picks
