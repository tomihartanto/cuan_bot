"""
CuanBot - Technical Indicators Calculator (Pure Python - No Pandas/NumPy)
RSI, MACD, Bollinger Bands, Volume Analysis
"""

from math import sqrt


def _sma(data: list, period: int) -> list:
    result = []
    for i in range(len(data)):
        if i < period - 1:
            result.append(None)
        else:
            window = data[i - period + 1:i + 1]
            result.append(sum(window) / period)
    return result


def _ema(data: list, period: int) -> list:
    k = 2 / (period + 1)
    result = [data[0]]
    for i in range(1, len(data)):
        result.append(data[i] * k + result[-1] * (1 - k))
    return result


def _rolling_std(data: list, period: int) -> list:
    result = []
    for i in range(len(data)):
        if i < period - 1:
            result.append(None)
        else:
            window = data[i - period + 1:i + 1]
            mean = sum(window) / period
            variance = sum((x - mean) ** 2 for x in window) / period
            result.append(sqrt(variance))
    return result


def calc_rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


def calc_macd(closes: list, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    if len(closes) < slow + signal:
        return {"macd": 0.0, "signal": 0.0, "histogram": 0.0, "prev_histogram": 0.0,
                "crossover_bullish": False, "crossover_bearish": False}
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = _ema(macd_line, signal)
    histogram = [m - s for m, s in zip(macd_line, signal_line)]
    h = histogram[-1] if len(histogram) > 0 else 0.0
    ph = histogram[-2] if len(histogram) > 1 else 0.0
    return {
        "macd": float(macd_line[-1]) if macd_line else 0.0,
        "signal": float(signal_line[-1]) if signal_line else 0.0,
        "histogram": float(h),
        "prev_histogram": float(ph),
        "crossover_bullish": ph <= 0 and h > 0,
        "crossover_bearish": ph >= 0 and h < 0,
    }


def calc_bollinger(closes: list, period: int = 20, std_dev: float = 2.0) -> dict:
    if len(closes) < period:
        current = closes[-1]
        return {"upper": current * 1.02, "middle": current, "lower": current * 0.98,
                "position": 0.5, "price": current, "below_lower": False, "above_upper": False}
    sma_vals = _sma(closes, period)
    std_vals = _rolling_std(closes, period)
    current_price = closes[-1]
    middle = sma_vals[-1]
    std = std_vals[-1] if std_vals[-1] is not None else 0
    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)
    band_width = upper - lower
    position = (current_price - lower) / band_width if band_width > 0 else 0.5
    position = max(0.0, min(1.0, position))
    return {
        "upper": float(upper), "middle": float(middle), "lower": float(lower),
        "position": float(position), "price": float(current_price),
        "below_lower": current_price < lower, "above_upper": current_price > upper,
    }


def calc_volume_trend(volumes: list, period: int = 20) -> dict:
    if len(volumes) < 1:
        return {"current": 0, "average": 0, "ratio": 1.0, "high_volume": False, "trend_up": False}
    current_vol = volumes[-1]
    if len(volumes) >= period:
        avg_vol = sum(volumes[-period:]) / period
    else:
        avg_vol = sum(volumes) / len(volumes)
    ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
    trend_up = False
    if len(volumes) >= 10:
        recent_avg = sum(volumes[-5:]) / 5
        older_avg = sum(volumes[-10:-5]) / 5
        trend_up = recent_avg > older_avg
    return {"current": float(current_vol), "average": float(avg_vol),
            "ratio": float(ratio), "high_volume": ratio > 1.5, "trend_up": trend_up}


def calc_ema_cross(closes: list, fast: int = 9, slow: int = 21) -> dict:
    """Hitung EMA crossover untuk sinyal momentum cepat (cocok scalping 5m)."""
    if len(closes) < slow + 2:
        return {"fast": 0.0, "slow": 0.0, "bullish_cross": False, "bearish_cross": False,
                "above": False, "gap_pct": 0.0}
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    # Current state
    curr_fast, curr_slow = ema_fast[-1], ema_slow[-1]
    prev_fast, prev_slow = ema_fast[-2], ema_slow[-2]
    above = curr_fast > curr_slow
    bullish_cross = (prev_fast <= prev_slow) and (curr_fast > curr_slow)  # cross ke atas
    bearish_cross = (prev_fast >= prev_slow) and (curr_fast < curr_slow)  # cross ke bawah
    gap_pct = ((curr_fast - curr_slow) / curr_slow * 100) if curr_slow != 0 else 0.0
    return {
        "fast": round(curr_fast, 4),
        "slow": round(curr_slow, 4),
        "bullish_cross": bullish_cross,
        "bearish_cross": bearish_cross,
        "above": above,           # True = fast di atas slow = uptrend
        "gap_pct": round(gap_pct, 3),
    }

