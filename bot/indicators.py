"""
CuanBot - Technical Indicators Calculator (Pure Python)
RSI, MACD, Bollinger Bands, Volume Analysis - No pandas/numpy
"""


def _sma(data: list, period: int) -> list:
    """Simple Moving Average."""
    result = []
    for i in range(len(data)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(sum(data[i - period + 1:i + 1]) / period)
    return result


def _ema(data: list, period: int) -> list:
    """Exponential Moving Average."""
    k = 2 / (period + 1)
    result = [data[0]]
    for i in range(1, len(data)):
        result.append(data[i] * k + result[-1] * (1 - k))
    return result


def _std(data: list, period: int) -> list:
    """Rolling Standard Deviation."""
    result = []
    for i in range(len(data)):
        if i < period - 1:
            result.append(None)
        else:
            window = data[i - period + 1:i + 1]
            mean = sum(window) / period
            variance = sum((x - mean) ** 2 for x in window) / period
            result.append(variance ** 0.5)
    return result


def calc_rsi(prices: list, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
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
    return 100.0 - (100.0 / (1.0 + rs))


def calc_macd(prices: list, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    if len(prices) < slow + signal:
        return {"macd": 0.0, "signal": 0.0, "histogram": 0.0, "prev_histogram": 0.0,
                "crossover_bullish": False, "crossover_bearish": False}
    ema_fast = _ema(prices, fast)
    ema_slow = _ema(prices, slow)
    macd_line = [ema_fast[i] - ema_slow[i] for i in range(len(prices))]
    signal_line = _ema(macd_line, signal)
    histogram = [macd_line[i] - signal_line[i] for i in range(len(prices))]
    return {
        "macd": macd_line[-1],
        "signal": signal_line[-1],
        "histogram": histogram[-1],
        "prev_histogram": histogram[-2] if len(histogram) > 1 else 0.0,
        "crossover_bullish": len(histogram) >= 2 and histogram[-2] <= 0 and histogram[-1] > 0,
        "crossover_bearish": len(histogram) >= 2 and histogram[-2] >= 0 and histogram[-1] < 0,
    }


def calc_bollinger(prices: list, period: int = 20, std_dev: float = 2.0) -> dict:
    if len(prices) < period:
        current = prices[-1]
        return {"upper": current * 1.02, "middle": current, "lower": current * 0.98,
                "position": 0.5, "price": current, "below_lower": False, "above_upper": False}
    sma_vals = _sma(prices, period)
    std_vals = _std(prices, period)
    middle = sma_vals[-1]
    s = std_vals[-1]
    upper = middle + s * std_dev
    lower = middle - s * std_dev
    current = prices[-1]
    band_width = upper - lower
    position = (current - lower) / band_width if band_width > 0 else 0.5
    position = max(0.0, min(1.0, position))
    return {
        "upper": upper, "middle": middle, "lower": lower,
        "position": position, "price": current,
        "below_lower": current < lower,
        "above_upper": current > upper,
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
    return {"current": current_vol, "average": avg_vol, "ratio": ratio, "high_volume": ratio > 1.5, "trend_up": trend_up}


def calc_price_change(prices: list) -> dict:
    current = prices[-1]
    changes = {}
    for periods, label in [(1, "1c"), (4, "4c"), (12, "12c"), (24, "24c")]:
        if len(prices) > periods:
            past = prices[-(periods + 1)]
            changes[label] = ((current - past) / past) * 100
        else:
            changes[label] = 0.0
    return {"current": current, "changes": changes,
            "trend_short": "up" if changes.get("4c", 0) > 0 else "down",
            "trend_medium": "up" if changes.get("12c", 0) > 0 else "down"}