from typing import Optional

import pandas as pd
import numpy as np
import ta

from config import (
    RSI_PERIOD, RSI_OVERBOUGHT, RSI_OVERSOLD,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    SUPERTREND_PERIOD, SUPERTREND_MULTIPLIER,
    STOP_LOSS_PCT, TARGET_PCT,
    MIN_INDICATORS_FOR_SIGNAL,
)


def compute_rsi(df: pd.DataFrame) -> dict:
    rsi = ta.momentum.RSIIndicator(df["Close"], window=RSI_PERIOD)
    values = rsi.rsi()
    value = round(float(values.iloc[-1]), 2)
    if value < RSI_OVERSOLD:
        signal = "BUY"
    elif value > RSI_OVERBOUGHT:
        signal = "SELL"
    else:
        signal = "NEUTRAL"
    return {"value": value, "signal": signal, "series": values}


def compute_macd(df: pd.DataFrame) -> dict:
    macd = ta.trend.MACD(
        df["Close"], window_fast=MACD_FAST, window_slow=MACD_SLOW, window_sign=MACD_SIGNAL
    )
    macd_line = macd.macd()
    signal_line = macd.macd_signal()
    histogram = macd.macd_diff()

    last_macd = round(float(macd_line.iloc[-1]), 2)
    last_signal = round(float(signal_line.iloc[-1]), 2)
    last_hist = round(float(histogram.iloc[-1]), 2)

    if last_macd > last_signal and last_hist > 0:
        signal = "BUY"
    elif last_macd < last_signal and last_hist < 0:
        signal = "SELL"
    else:
        signal = "NEUTRAL"
    return {
        "macd_line": last_macd, "signal_line": last_signal, "histogram": last_hist,
        "signal": signal,
        "macd_series": macd_line, "signal_series": signal_line, "hist_series": histogram,
    }


def compute_supertrend(df: pd.DataFrame) -> dict:
    high = df["High"].values
    low = df["Low"].values
    close = df["Close"].values

    atr_series = ta.volatility.AverageTrueRange(
        pd.Series(high), pd.Series(low), pd.Series(close), window=SUPERTREND_PERIOD
    ).average_true_range()

    hl2 = (pd.Series(high) + pd.Series(low)) / 2
    upper_band = hl2 + (SUPERTREND_MULTIPLIER * atr_series)
    lower_band = hl2 - (SUPERTREND_MULTIPLIER * atr_series)

    supertrend = pd.Series(np.zeros(len(close)), index=df.index)
    direction = [1] * len(close)

    for i in range(1, len(close)):
        if close[i] > upper_band.iloc[i - 1]:
            direction[i] = 1
        elif close[i] < lower_band.iloc[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]

        if direction[i] == 1:
            supertrend.iloc[i] = lower_band.iloc[i]
        else:
            supertrend.iloc[i] = upper_band.iloc[i]

    current_direction = direction[-1]
    signal = "BUY" if current_direction == 1 else "SELL"
    return {
        "value": round(float(supertrend.iloc[-1]), 2),
        "direction": current_direction,
        "signal": signal,
        "series": supertrend,
        "direction_series": direction,
    }


def compute_vwap(df: pd.DataFrame) -> dict:
    vwap = ta.volume.VolumeWeightedAveragePrice(
        high=df["High"], low=df["Low"], close=df["Close"], volume=df["Volume"]
    )
    vwap_series = vwap.volume_weighted_average_price()
    vwap_value = round(float(vwap_series.iloc[-1]), 2)
    current_price = round(float(df["Close"].iloc[-1]), 2)

    if current_price > vwap_value:
        signal = "BUY"
    elif current_price < vwap_value:
        signal = "SELL"
    else:
        signal = "NEUTRAL"
    return {"value": vwap_value, "current_price": current_price, "signal": signal, "series": vwap_series}


def evaluate_oi(oi_data: Optional[dict]) -> dict:
    if not oi_data:
        return {"signal": "NEUTRAL", "pcr": 0, "net_oi_change": 0}

    pcr = oi_data["pcr"]
    net_oi_change = oi_data["net_oi_change"]

    if pcr > 1.2 and net_oi_change > 0:
        signal = "BUY"
    elif pcr < 0.8 and net_oi_change < 0:
        signal = "SELL"
    else:
        signal = "NEUTRAL"
    return {"signal": signal, "pcr": pcr, "net_oi_change": net_oi_change}


def compute_support_resistance(df: pd.DataFrame) -> dict:
    """Compute 2 support, 2 resistance, and pivot from recent price data."""
    high = float(df["High"].max())
    low = float(df["Low"].min())
    close = float(df["Close"].iloc[-1])

    pivot = round((high + low + close) / 3, 2)
    r1 = round(2 * pivot - low, 2)
    r2 = round(pivot + (high - low), 2)
    s1 = round(2 * pivot - high, 2)
    s2 = round(pivot - (high - low), 2)

    return {
        "pivot": pivot,
        "r1": r1, "r2": r2,
        "s1": s1, "s2": s2,
    }


def compute_all_signals(df: pd.DataFrame, interval: str = "5m") -> list:
    """Detect high-quality crossover signals on the chart.

    Designed to produce only 2-5 signals per trading day.
    Requires at least 1 actual crossover (MACD cross, SuperTrend flip, or VWAP cross)
    PLUS supporting confirmation to fire.

    MIN_GAP between signals is scaled by timeframe:
      1m  -> 90 candles (1.5 hours between signals)
      5m  -> 24 candles (2 hours between signals)
      15m -> 8 candles  (2 hours between signals)
      30m -> 4 candles  (2 hours between signals)
      1h  -> 2 candles  (2 hours between signals)
    """
    if len(df) < MACD_SLOW + MACD_SIGNAL + 1:
        return []

    # Scale gap so we get ~2-5 trades per day regardless of interval
    gap_map = {"1m": 90, "5m": 15, "15m": 6, "30m": 3, "1h": 2}
    MIN_GAP = gap_map.get(interval, 15)

    rsi_ind = ta.momentum.RSIIndicator(df["Close"], window=RSI_PERIOD).rsi()
    macd_obj = ta.trend.MACD(df["Close"], window_fast=MACD_FAST, window_slow=MACD_SLOW, window_sign=MACD_SIGNAL)
    macd_line = macd_obj.macd()
    signal_line = macd_obj.macd_signal()

    vwap_obj = ta.volume.VolumeWeightedAveragePrice(
        high=df["High"], low=df["Low"], close=df["Close"], volume=df["Volume"]
    )
    vwap_series = vwap_obj.volume_weighted_average_price()

    high = df["High"].values
    low = df["Low"].values
    close = df["Close"].values
    atr_series = ta.volatility.AverageTrueRange(
        pd.Series(high), pd.Series(low), pd.Series(close), window=SUPERTREND_PERIOD
    ).average_true_range()
    hl2 = (pd.Series(high) + pd.Series(low)) / 2
    upper_band = hl2 + (SUPERTREND_MULTIPLIER * atr_series)
    lower_band = hl2 - (SUPERTREND_MULTIPLIER * atr_series)
    st_direction = [0] * len(close)
    if len(close) > 0:
        st_direction[0] = 1
    for i in range(1, len(close)):
        if close[i] > upper_band.iloc[i - 1]:
            st_direction[i] = 1
        elif close[i] < lower_band.iloc[i - 1]:
            st_direction[i] = -1
        else:
            st_direction[i] = st_direction[i - 1]

    signals = []
    last_signal_i = -999

    start = MACD_SLOW + MACD_SIGNAL
    for i in range(start, len(df)):
        if i - last_signal_i < MIN_GAP:
            continue

        rsi_val = rsi_ind.iloc[i]
        prev_macd = macd_line.iloc[i - 1] if not pd.isna(macd_line.iloc[i - 1]) else None
        prev_sig = signal_line.iloc[i - 1] if not pd.isna(signal_line.iloc[i - 1]) else None
        curr_macd = macd_line.iloc[i] if not pd.isna(macd_line.iloc[i]) else None
        curr_sig = signal_line.iloc[i] if not pd.isna(signal_line.iloc[i]) else None
        curr_vwap = vwap_series.iloc[i] if not pd.isna(vwap_series.iloc[i]) else None
        prev_close = close[i - 1]
        prev_vwap = vwap_series.iloc[i - 1] if not pd.isna(vwap_series.iloc[i - 1]) else None

        buy_crossovers = 0
        sell_crossovers = 0
        buy_confirm = 0
        sell_confirm = 0

        # ── CROSSOVER signals (must have at least 1) ──

        # 1. MACD crossover (strongest signal)
        if prev_macd is not None and prev_sig is not None and curr_macd is not None and curr_sig is not None:
            if prev_macd <= prev_sig and curr_macd > curr_sig:
                buy_crossovers += 1
            elif prev_macd >= prev_sig and curr_macd < curr_sig:
                sell_crossovers += 1

        # 2. SuperTrend flip
        if i > 0:
            if st_direction[i] == 1 and st_direction[i - 1] == -1:
                buy_crossovers += 1
            elif st_direction[i] == -1 and st_direction[i - 1] == 1:
                sell_crossovers += 1

        # 3. VWAP cross
        if curr_vwap is not None and prev_vwap is not None:
            if prev_close <= prev_vwap and close[i] > curr_vwap:
                buy_crossovers += 1
            elif prev_close >= prev_vwap and close[i] < curr_vwap:
                sell_crossovers += 1

        # ── CONFIRMATION signals (support but don't trigger alone) ──

        # 4. RSI zone
        if not pd.isna(rsi_val):
            if rsi_val < 45:
                buy_confirm += 1
            elif rsi_val > 55:
                sell_confirm += 1

        # 5. Trend alignment
        if st_direction[i] == 1:
            buy_confirm += 1
        else:
            sell_confirm += 1

        # 6. Price vs VWAP
        if curr_vwap is not None:
            if close[i] > curr_vwap:
                buy_confirm += 1
            else:
                sell_confirm += 1

        # ── SIGNAL RULES ──
        # Need crossover + confirmation. Stronger crossovers need less confirmation.
        # 2+ crossovers -> fire with any 1 confirmation
        # 1 crossover   -> need 2+ confirmations
        buy_total = buy_crossovers + buy_confirm
        sell_total = sell_crossovers + sell_confirm
        buy_ok = (buy_crossovers >= 2 and buy_confirm >= 1) or (buy_crossovers >= 1 and buy_confirm >= 2)
        sell_ok = (sell_crossovers >= 2 and sell_confirm >= 1) or (sell_crossovers >= 1 and sell_confirm >= 2)

        if buy_ok and buy_total > sell_total:
            signals.append({
                "index": df.index[i],
                "price": close[i],
                "action": "BUY",
                "sl": round(close[i] * (1 - STOP_LOSS_PCT / 100), 2),
                "target": round(close[i] * (1 + TARGET_PCT / 100), 2),
            })
            last_signal_i = i
        elif sell_ok and sell_total > buy_total:
            signals.append({
                "index": df.index[i],
                "price": close[i],
                "action": "SELL",
                "sl": round(close[i] * (1 + STOP_LOSS_PCT / 100), 2),
                "target": round(close[i] * (1 - TARGET_PCT / 100), 2),
            })
            last_signal_i = i

    return signals


def generate_signal(
    rsi: dict, macd: dict, supertrend: dict, vwap: dict, oi: dict, spot_price: float
) -> dict:
    indicators = [rsi["signal"], macd["signal"], supertrend["signal"], vwap["signal"], oi["signal"]]

    buy_count = indicators.count("BUY")
    sell_count = indicators.count("SELL")

    if buy_count >= MIN_INDICATORS_FOR_SIGNAL:
        action = "BUY"
        stop_loss = round(spot_price * (1 - STOP_LOSS_PCT / 100), 2)
        target = round(spot_price * (1 + TARGET_PCT / 100), 2)
    elif sell_count >= MIN_INDICATORS_FOR_SIGNAL:
        action = "SELL"
        stop_loss = round(spot_price * (1 + STOP_LOSS_PCT / 100), 2)
        target = round(spot_price * (1 - TARGET_PCT / 100), 2)
    else:
        action = "HOLD"
        stop_loss = None
        target = None

    return {
        "action": action,
        "entry_price": spot_price,
        "stop_loss": stop_loss,
        "target": target,
        "buy_count": buy_count,
        "sell_count": sell_count,
        "neutral_count": indicators.count("NEUTRAL"),
    }
