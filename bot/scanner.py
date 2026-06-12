"""
CuanBot - Smart Scoring Engine
Combines all technical indicators into a single score (0-100)
"""

import pandas as pd
from bot.indicators import calc_rsi, calc_macd, calc_bollinger, calc_volume_trend, calc_price_change
from config import Config


def score_coin(candles: list) -> dict:
    if len(candles) < 30:
        return {"score": 50, "signals": {}, "action": "HOLD", "reason": "Data tidak cukup"}

    df = pd.DataFrame(candles)
    close = df["close"].astype(float)
    volume = df["volume"].astype(float)

    rsi = calc_rsi(close, Config.RSI_PERIOD)
    macd = calc_macd(close, Config.MACD_FAST, Config.MACD_SLOW, Config.MACD_SIGNAL)
    bb = calc_bollinger(close, Config.BB_PERIOD, Config.BB_STD)
    vol = calc_volume_trend(volume, Config.VOLUME_MA_PERIOD)
    price = calc_price_change(close)

    # RSI Score (0-25)
    if rsi < 20: rsi_score = 25
    elif rsi < 30: rsi_score = 22
    elif rsi < 40: rsi_score = 18
    elif rsi < 50: rsi_score = 14
    elif rsi < 60: rsi_score = 10
    elif rsi < 70: rsi_score = 6
    elif rsi < 80: rsi_score = 3
    else: rsi_score = 0

    # MACD Score (0-25)
    macd_score = 10
    if macd["crossover_bullish"]: macd_score = 25
    elif macd["histogram"] > 0 and macd["prev_histogram"] > 0: macd_score = 20
    elif macd["histogram"] > 0: macd_score = 15
    elif macd["crossover_bearish"]: macd_score = 0
    elif macd["histogram"] < 0: macd_score = 5

    # Bollinger Score (0-25) - lower position = higher score (buy signal)
    bb_score = max(0, min(25, int(25 - bb["position"] * 25)))
    if bb["below_lower"]: bb_score = 25
    elif bb["above_upper"]: bb_score = 0

    # Volume Score (0-25)
    vol_score = 10
    if vol["high_volume"] and rsi < 40: vol_score = 22
    elif vol["high_volume"] and rsi > 60: vol_score = 5
    elif vol["trend_up"]: vol_score = 15
    else: vol_score = 8

    total_score = rsi_score + macd_score + bb_score + vol_score

    if total_score >= Config.MIN_SCORE_TO_BUY: action = "BUY"
    elif total_score <= Config.MIN_SCORE_TO_HOLD: action = "SELL"
    else: action = "HOLD"

    reasons = []
    if rsi < 30: reasons.append(f"RSI oversold ({rsi:.1f})")
    elif rsi > 70: reasons.append(f"RSI overbought ({rsi:.1f})")
    if macd["crossover_bullish"]: reasons.append("MACD bullish crossover")
    elif macd["crossover_bearish"]: reasons.append("MACD bearish crossover")
    if bb["below_lower"]: reasons.append("Price below lower BB")
    elif bb["above_upper"]: reasons.append("Price above upper BB")
    if vol["high_volume"]: reasons.append(f"High volume ({vol['ratio']:.1f}x)")
    reason = " | ".join(reasons) if reasons else "No strong signals"

    return {
        "score": total_score,
        "signals": {
            "rsi": {"value": round(rsi, 1), "score": rsi_score},
            "macd": {"hist": round(macd["histogram"], 4), "score": macd_score, "bullish_cross": macd["crossover_bullish"]},
            "bb": {"position": round(bb["position"], 2), "score": bb_score},
            "volume": {"ratio": round(vol["ratio"], 2), "score": vol_score},
            "price_change": price["changes"],
        },
        "action": action,
        "reason": reason,
        "price": price["current"],
    }
