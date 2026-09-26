"""Market data endpoints: indices, scanner, sector picks, option chain, news."""
from fastapi import APIRouter, HTTPException, Query

from app.core.cache import TTLCache
from app.services import zerodha
from app.core.config import SYMBOLS
from app.services.market_data import _CHART_TF, get_chart_candles, get_nse_indices, get_option_chain_nse_direct, is_market_open
from app.services.news import scrape_moneycontrol_news
from app.services.scanner import SECTOR_UNIVERSE, TF_YF_MAP, run_scanner
from app.services.sector_watchlist import SECTOR_STOCKS

router = APIRouter(prefix="/api", tags=["market"])

# Many tabs polling must not each trigger a scan / scrape / Kite call.
_cache = TTLCache("market")


@router.get("/indices")
def indices():
    try:
        return _cache.get("indices", ttl=10, compute=get_nse_indices, stale_ttl=120)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Indices unavailable: {e}")


@router.get("/scanner")
def scanner(timeframe: str = Query("15m")):
    """Run signal scoring on all sector universe stocks. Returns sorted list by score."""
    if timeframe not in TF_YF_MAP:
        raise HTTPException(status_code=400, detail=f"Unknown timeframe '{timeframe}'")
    use_kite = zerodha.is_connected()
    ttl = 30 if is_market_open() else 300
    try:
        return _cache.get(("scanner", timeframe, use_kite), ttl=ttl,
                          compute=lambda: run_scanner(SECTOR_UNIVERSE, timeframe, use_kite), stale_ttl=ttl * 20)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Scanner failed: {e}")


@router.get("/sector-picks")
def sector_picks(sector: str = Query(...), timeframe: str = Query("15m")):
    """Return top 4 stocks in a sector with signal data."""
    stocks = SECTOR_STOCKS.get(sector)
    if not stocks:
        raise HTTPException(status_code=404, detail=f"Sector '{sector}' not found")
    if timeframe not in TF_YF_MAP:
        raise HTTPException(status_code=400, detail=f"Unknown timeframe '{timeframe}'")
    use_kite = zerodha.is_connected()
    ttl = 30 if is_market_open() else 300
    try:
        results = _cache.get(("sector", sector, timeframe, use_kite), ttl=ttl,
                             compute=lambda: run_scanner(tuple(stocks), timeframe, use_kite), stale_ttl=ttl * 20)
        return results[:4]
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Sector scan failed: {e}")


def _load_option_chain(symbol: str):
    if zerodha.is_connected():
        try:
            data = zerodha.get_option_chain_kite(symbol)
            if data:
                return data
        except Exception as e:
            print(f"[api] kite option chain failed for {symbol}: {e}")
    data = get_option_chain_nse_direct(symbol)   # NSE blocks scripted requests often; may be empty
    if not data:
        raise RuntimeError("no data from Kite or NSE")
    return data


@router.get("/option-chain")
def option_chain(symbol: str = Query("NIFTY")):
    """Option chain from Kite when logged in, else NSE. Cached briefly and served stale if NSE blocks us."""
    symbol = symbol.strip().upper()
    if not symbol or len(symbol) > 20:
        raise HTTPException(status_code=400, detail="Invalid symbol")
    ttl = 20 if is_market_open() else 300
    try:
        return _cache.get(("oc", symbol), ttl=ttl, compute=lambda: _load_option_chain(symbol), stale_ttl=ttl * 30)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Option chain unavailable for {symbol} ({e}). NSE often blocks server requests — log in to Zerodha Kite for a reliable feed.",
        )


@router.get("/candles")
def candles(symbol: str = Query(...), timeframe: str = Query("5m")):
    """OHLCV bars for the dashboard chart. Times are UTC epoch seconds."""
    symbol = symbol.strip().upper()
    if not symbol or len(symbol) > 30:
        raise HTTPException(status_code=400, detail="Invalid symbol")
    if timeframe not in _CHART_TF:
        raise HTTPException(status_code=400, detail=f"Unknown timeframe '{timeframe}'")

    def _load():
        source, df = get_chart_candles(symbol, timeframe)
        if df.empty:
            raise RuntimeError("no candles")
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "source": source,
            "candles": [
                {"time": int(ts.timestamp()), "open": round(float(r.Open), 2), "high": round(float(r.High), 2),
                 "low": round(float(r.Low), 2), "close": round(float(r.Close), 2), "volume": int(r.Volume or 0)}
                for ts, r in df.iterrows()
            ],
        }

    ttl = 15 if is_market_open() else 600
    try:
        return _cache.get(("candles", symbol, timeframe), ttl=ttl, compute=_load, stale_ttl=ttl * 4)
    except Exception:
        raise HTTPException(status_code=404, detail=f"No chart data for {symbol}. Check the symbol name (NSE code, e.g. INFY).")


_FO_INDICES = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"]


def _load_fo_symbols():
    names = set(zerodha.get_fo_underlying_symbols() if zerodha.is_connected() else [])
    if not names:  # logged out: the stocks we know are F&O-listed
        names = set(SECTOR_UNIVERSE) | {v["nse"] for v in SYMBOLS.values() if v["nse"]}
    return _FO_INDICES + sorted(names - set(_FO_INDICES))


@router.get("/fo-symbols")
def fo_symbols():
    """Underlyings that have an option chain: indices first, then stocks A-Z."""
    try:
        return _cache.get(("fo-symbols", zerodha.is_connected()), ttl=6 * 3600, compute=_load_fo_symbols)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"F&O symbol list unavailable: {e}")


@router.get("/news")
def news():
    """Top 10 news items from MoneyControl."""
    try:
        return _cache.get(
            "news", ttl=600, stale_ttl=6 * 3600,
            compute=lambda: [{**i, "title": i.get("headline", "")} for i in (scrape_moneycontrol_news() or [])[:10]],
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"News unavailable: {e}")
