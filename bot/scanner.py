"""
CuanBot - Smart Scoring Engine v3
Multi-timeframe + EMA crossover untuk scalping cepat.
(Pure Python - No Pandas)
"""

from bot.indicators import calc_rsi, calc_macd, calc_bollinger, calc_volume_trend, calc_price_change, calc_ema_cross
from config import Config


def score_coin(candles: list) -> dict:
    """Score coin dari single-timeframe candles. Total skor: 100."""
    if len(candles) < 30:
        return {"score": 50, "signals": {}, "action": "HOLD", "reason": "Data kurang"}

    closes  = [float(c["close"]) for c in candles]
    volumes = [float(c["volume"]) for c in candles]

    rsi  = calc_rsi(closes, Config.RSI_PERIOD)
    macd = calc_macd(closes, Config.MACD_FAST, Config.MACD_SLOW, Config.MACD_SIGNAL)
    bb   = calc_bollinger(closes, Config.BB_PERIOD, Config.BB_STD)
    vol  = calc_volume_trend(volumes, Config.VOLUME_MA_PERIOD)
    price = calc_price_change(closes)
    ema  = calc_ema_cross(closes, fast=9, slow=21)

    # ── RSI Score (0-25) ─────────────────────────────────────────────
    if   rsi < 20: rsi_score = 25
    elif rsi < 30: rsi_score = 23
    elif rsi < 40: rsi_score = 18
    elif rsi < 50: rsi_score = 13
    elif rsi < 60: rsi_score =  9
    elif rsi < 70: rsi_score =  5
    elif rsi < 80: rsi_score =  2
    else:          rsi_score =  0

    # ── MACD Score (0-20) ─────────────────────────────────────────────
    if   macd["crossover_bullish"]:                                macd_score = 20
    elif macd["histogram"] > 0 and macd["prev_histogram"] > 0:    macd_score = 16
    elif macd["histogram"] > 0:                                    macd_score = 12
    elif macd["crossover_bearish"]:                                macd_score =  0
    elif macd["histogram"] < 0:                                    macd_score =  4
    else:                                                          macd_score =  8

    # ── Bollinger Score (0-20) ────────────────────────────────────────
    bb_score = max(0, min(20, int(20 - bb["position"] * 20)))
    if bb["below_lower"]:  bb_score = 20
    elif bb["above_upper"]: bb_score = 0

    # ── EMA Crossover Score (0-20) ────────────────────────────────────
    # Sinyal momentum utama untuk scalping
    if   ema["bullish_cross"]:                     ema_score = 20   # Fresh cross = sinyal terkuat
    elif ema["above"] and ema["gap_pct"] > 0.3:   ema_score = 16   # Uptrend kuat
    elif ema["above"] and ema["gap_pct"] > 0.0:   ema_score = 12   # Uptrend lemah
    elif ema["bearish_cross"]:                     ema_score =  0   # Fresh bearish cross
    elif not ema["above"] and ema["gap_pct"] < -0.3: ema_score = 2  # Downtrend kuat
    else:                                          ema_score =  8   # Netral

    # ── Volume Score (0-15) ───────────────────────────────────────────
    if   vol["high_volume"] and rsi < 40: vol_score = 15   # Volume spike + oversold
    elif vol["high_volume"] and rsi > 60: vol_score =  4   # Volume spike tapi overbought
    elif vol["trend_up"]:                 vol_score = 10
    else:                                 vol_score =  6

    total_score = rsi_score + macd_score + bb_score + ema_score + vol_score

    if   total_score >= Config.MIN_SCORE_TO_BUY:  action = "BUY"
    elif total_score <= Config.MIN_SCORE_TO_HOLD: action = "SELL"
    else:                                          action = "HOLD"

    # Reason string
    reasons = []
    if rsi < 30:                       reasons.append(f"RSI oversold ({rsi:.1f})")
    elif rsi > 70:                     reasons.append(f"RSI overbought ({rsi:.1f})")
    if macd["crossover_bullish"]:      reasons.append("MACD bullish cross")
    elif macd["crossover_bearish"]:    reasons.append("MACD bearish cross")
    if bb["below_lower"]:              reasons.append("Below lower BB")
    elif bb["above_upper"]:            reasons.append("Above upper BB")
    if ema["bullish_cross"]:           reasons.append("EMA9/21 bullish cross 🚀")
    elif ema["bearish_cross"]:         reasons.append("EMA9/21 bearish cross ⚠️")
    elif ema["above"]:                 reasons.append(f"EMA uptrend ({ema['gap_pct']:+.2f}%)")
    if vol["high_volume"]:             reasons.append(f"Volume spike ({vol['ratio']:.1f}x)")
    reason = " | ".join(reasons) if reasons else "No strong signals"

    return {
        "score": total_score,
        "signals": {
            "rsi":    {"value": round(rsi, 1),              "score": rsi_score},
            "macd":   {"hist": round(macd["histogram"], 4), "score": macd_score, "bullish": macd["crossover_bullish"]},
            "bb":     {"position": round(bb["position"], 2),"score": bb_score},
            "ema":    {"above": ema["above"],               "score": ema_score,  "cross": ema["bullish_cross"], "gap": ema["gap_pct"]},
            "volume": {"ratio": round(vol["ratio"], 2),     "score": vol_score},
            "price_change": price["changes"],
        },
        "action": action, "reason": reason, "price": price["current"],
    }


def score_coin_multi_tf(candles_by_tf: dict) -> dict:
    """Score coin dengan multi-timeframe weighted average."""
    scores = {}
    for tf, candles in candles_by_tf.items():
        result = score_coin(candles)
        scores[tf] = result

    # Weighted average
    total_weight = 0
    weighted_score = 0
    for tf, weight in Config.TIMEFRAME_WEIGHTS.items():
        if tf in scores:
            weighted_score += scores[tf]["score"] * weight
            total_weight += weight

    if total_weight == 0:
        return scores.get(Config.TIMEFRAME, {"score": 50, "action": "HOLD", "reason": "No data"})

    final_score = int(weighted_score / total_weight)

    # Gunakan timeframe terpendek untuk price dan signals
    primary = scores.get(Config.TIMEFRAME, scores.get("5m", {}))

    # Bonus kalau multi-TF sepakat BUY
    buy_count = sum(1 for s in scores.values() if s["action"] == "BUY")
    if buy_count >= 2: final_score = min(100, final_score + 10)
    if buy_count == 3: final_score = min(100, final_score + 5)

    # Bonus kalau ada EMA bullish cross di TF manapun
    ema_cross_any = any(
        s.get("signals", {}).get("ema", {}).get("cross", False)
        for s in scores.values()
    )
    if ema_cross_any:
        final_score = min(100, final_score + 5)

    if   final_score >= Config.MIN_SCORE_TO_BUY:  action = "BUY"
    elif final_score <= Config.MIN_SCORE_TO_HOLD: action = "SELL"
    else:                                          action = "HOLD"

    all_reasons = set()
    for s in scores.values():
        if s["reason"] != "No strong signals":
            all_reasons.add(s["reason"])
    reason = " | ".join(all_reasons) if all_reasons else "No strong signals"
    if buy_count >= 2:
        reason += f" | Multi-TF confirm ({buy_count}/3)"
    if ema_cross_any:
        reason += " | EMA cross confirmed ✅"

    return {
        "score": final_score,
        "signals": {tf: s["signals"] for tf, s in scores.items()},
        "action": action,
        "reason": reason,
        "price": primary.get("price", 0),
        "multi_tf": {tf: {"score": s["score"], "action": s["action"]} for tf, s in scores.items()},
    }
