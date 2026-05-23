from typing import Optional
import concurrent.futures
import time

import yfinance as yf
import pandas as pd
from datetime import datetime
import pytz

from config import (
    MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE,
    MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE,
)

IST = pytz.timezone("Asia/Kolkata")


def is_market_open() -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(
        hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0
    )
    market_close = now.replace(
        hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0, microsecond=0
    )
    return market_open <= now <= market_close


def get_spot_price(symbol: str) -> Optional[float]:
    """Fetch latest price — fast_info first (fastest), fallback to history."""
    # Try fast_info first (no data download needed — much faster)
    try:
        ticker = yf.Ticker(symbol)
        price = ticker.fast_info.get("lastPrice") or ticker.fast_info.get("regularMarketPrice")
        if price:
            return round(float(price), 2)
    except Exception:
        pass
    # Fallback: history
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="1d", interval="1m")
        if data.empty:
            data = ticker.history(period="5d", interval="5m")
        if not data.empty:
            return round(float(data["Close"].iloc[-1]), 2)
    except Exception:
        pass
    return None


def get_intraday_data(symbol: str, period: str = "5d", interval: str = "5m") -> pd.DataFrame:
    """Fetch intraday OHLCV — single attempt, fast."""
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)
        if not df.empty:
            return df
    except Exception:
        pass
    # One fallback with shorter period
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="1d", interval=interval)
        if not df.empty:
            return df
    except Exception:
        pass
    return pd.DataFrame()


def _fetch_option_chain_inner(symbol_nse: str) -> Optional[dict]:
    try:
        from nsepython import option_chain
    except ImportError:
        return None

    try:
        data = option_chain(symbol_nse)
    except Exception:
        return None

    if data is not None and "records" in data:
        records = data["records"]
        total_ce_oi = 0
        total_pe_oi = 0
        total_ce_oi_change = 0
        total_pe_oi_change = 0

        for item in records.get("data", []):
            if "CE" in item:
                total_ce_oi += item["CE"].get("openInterest", 0)
                total_ce_oi_change += item["CE"].get("changeinOpenInterest", 0)
            if "PE" in item:
                total_pe_oi += item["PE"].get("openInterest", 0)
                total_pe_oi_change += item["PE"].get("changeinOpenInterest", 0)

        pcr = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 0
        return {
            "ce_oi": total_ce_oi,
            "pe_oi": total_pe_oi,
            "ce_oi_change": total_ce_oi_change,
            "pe_oi_change": total_pe_oi_change,
            "pcr": pcr,
            "net_oi_change": total_pe_oi_change - total_ce_oi_change,
        }
    return None


def get_option_chain_data(symbol_nse: str) -> Optional[dict]:
    if not symbol_nse:
        return None
    try:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(_fetch_option_chain_inner, symbol_nse)
            return future.result(timeout=15)
    except Exception:
        return None


def get_option_recommendation(symbol_nse: str, spot_price: float, action: str) -> Optional[dict]:
    """Given a signal (BUY/SELL), recommend the best option contract to trade."""
    try:
        from nsepython import option_chain
        data = option_chain(symbol_nse)
        if data is None or "records" not in data:
            return None

        records = data["records"]
        expiry_dates = records.get("expiryDates", [])
        nearest_expiry = expiry_dates[0] if expiry_dates else None
        all_strikes = records.get("strikePrices", [])

        atm_strike = min(all_strikes, key=lambda s: abs(s - spot_price)) if all_strikes else None
        if atm_strike is None:
            return None

        option_type = "CE" if action == "BUY" else "PE"

        step = 50 if symbol_nse in ("NIFTY", "BANKNIFTY") else 100
        if option_type == "CE":
            strikes_to_check = [atm_strike, atm_strike + step]
        else:
            strikes_to_check = [atm_strike, atm_strike - step]

        best_option = None
        for item in records.get("data", []):
            strike = item.get("strikePrice", 0)
            if strike not in strikes_to_check:
                continue
            if option_type not in item:
                continue
            opt = item[option_type]
            if opt.get("expiryDate") != nearest_expiry:
                continue

            ltp = opt.get("lastPrice", 0)
            oi_val = opt.get("openInterest", 0)
            oi_change = opt.get("changeinOpenInterest", 0)
            iv = opt.get("impliedVolatility", 0)
            bid = opt.get("bidprice", 0)
            ask = opt.get("askprice", 0)

            entry = {
                "strike": strike,
                "type": option_type,
                "expiry": nearest_expiry,
                "ltp": ltp,
                "bid": bid,
                "ask": ask,
                "oi": oi_val,
                "oi_change": oi_change,
                "iv": iv,
                "contract": f"{symbol_nse} {int(strike)} {option_type}",
            }

            if best_option is None or strike == atm_strike:
                best_option = entry

        if best_option:
            lot_sizes = {"NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 40}
            lot = lot_sizes.get(symbol_nse, 1)
            best_option["lot_size"] = lot
            best_option["total_premium"] = round(best_option["ltp"] * lot, 2)
            if action == "BUY":
                best_option["premium_sl"] = round(best_option["ltp"] * 0.7, 2)
                best_option["premium_target"] = round(best_option["ltp"] * 1.5, 2)
            else:
                best_option["premium_sl"] = round(best_option["ltp"] * 0.7, 2)
                best_option["premium_target"] = round(best_option["ltp"] * 1.5, 2)
            best_option["premium_avg"] = round(best_option["ltp"] * 0.7, 2)  # average at 30% below entry

        return best_option
    except Exception:
        return None


def get_current_option_ltp(symbol_nse: str, strike: float, option_type: str, expiry: str) -> Optional[float]:
    """Fetch the current LTP of a specific option contract from NSE option chain.

    Returns the last traded price as a float, or None if fetch fails.
    """
    if not symbol_nse:
        return None
    try:
        from nsepython import option_chain
        data = option_chain(symbol_nse)
        if data is None or "records" not in data:
            return None

        for item in data["records"].get("data", []):
            if item.get("strikePrice") != strike:
                continue
            if option_type not in item:
                continue
            opt = item[option_type]
            if opt.get("expiryDate") != expiry:
                continue
            ltp = opt.get("lastPrice", 0)
            if ltp > 0:
                return round(float(ltp), 2)
        return None
    except Exception:
        return None


def get_prices(nifty_sym: str = "^NSEI", banknifty_sym: str = "^NSEBANK") -> dict:
    nifty = get_spot_price(nifty_sym)
    banknifty = get_spot_price(banknifty_sym)
    return {"nifty": nifty, "banknifty": banknifty}
