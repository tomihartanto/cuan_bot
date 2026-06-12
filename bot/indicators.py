"""
CuanBot - Technical Indicators Calculator
RSI, MACD, Bollinger Bands, Volume Analysis
"""

import numpy as np
import pandas as pd


def calc_rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    avg_gain = avg_gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = avg_loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty and not pd.isna(rsi.iloc[-1]) else 50.0


def calc_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return {
        "macd": float(macd_line.iloc[-1]) if len(macd_line) > 0 else 0.0,
        "signal": float(signal_line.iloc[-1]) if len(signal_line) > 0 else 0.0,
        "histogram": float(histogram.iloc[-1]) if len(histogram) > 0 else 0.0,
        "prev_histogram": float(histogram.iloc[-2]) if len(histogram) > 1 else 0.0,
        "crossover_bullish": len(histogram) >= 2 and histogram.iloc[-2] <= 0 and histogram.iloc[-1] > 0,
        "crossover_bearish": len(histogram) >= 2 and histogram.iloc[-2] >= 0 and histogram.iloc[-1] < 0,
    }


def calc_bollinger(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> dict:
    sma = series.rolling(window=period).mean()
    rolling_std = series.rolling(window=period).std()
    upper = sma + (rolling_std * std_dev)
    lower = sma - (rolling_std * std_dev)
    current_price = float(series.iloc[-1])
    upper_val = float(upper.iloc[-1]) if not upper.empty and not pd.isna(upper.iloc[-1]) else current_price * 1.02
    lower_val = float(lower.iloc[-1]) if not lower.empty and not pd.isna(lower.iloc[-1]) else current_price * 0.98
    middle_val = float(sma.iloc[-1]) if not sma.empty and not pd.isna(sma.iloc[-1]) else current_price
    band_width = upper_val - lower_val
    position = (current_price - lower_val) / band_width if band_width > 0 else 0.5
    return {
        "upper": upper_val, "middle": middle_val, "lower": lower_val,
        "position": float(np.clip(position, 0, 1)),
        "price": current_price,
        "below_lower": current_price < lower_val,
        "above_upper": current_price > upper_val,
    }


def calc_volume_trend(volume: pd.Series, period: int = 20) -> dict:
    vol_ma = volume.rolling(window=period).mean()
    current_vol = float(volume.iloc[-1])
    avg_vol = float(vol_ma.iloc[-1]) if not vol_ma.empty and not pd.isna(vol_ma.iloc[-1]) else current_vol
    ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
    if len(volume) >= 5:
        recent_avg = float(volume.iloc[-5:].mean())
        older_avg = float(volume.iloc[-10:-5].mean()) if len(volume) >= 10 else recent_avg
        trend_up = recent_avg > older_avg
    else:
        trend_up = False
    return {"current": current_vol, "average": avg_vol, "ratio": ratio, "high_volume": ratio > 1.5, "trend_up": trend_up}


def calc_price_change(series: pd.Series) -> dict:
    current = float(series.iloc[-1])
    changes = {}
    for periods, label in [(1, "1c"), (4, "4c"), (12, "12c"), (24, "24c")]:
        if len(series) > periods:
            past = float(series.iloc[-(periods + 1)])
            changes[label] = ((current - past) / past) * 100
        else:
            changes[label] = 0.0
    return {"current": current, "changes": changes,
            "trend_short": "up" if changes.get("4c", 0) > 0 else "down",
            "trend_medium": "up" if changes.get("12c", 0) > 0 else "down"}
