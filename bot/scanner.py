"""
CuanBot - Smart Scoring Engine v4
Multi-timeframe + EMA crossover + Falling Knife Filter.
Recalibrated untuk kondisi market normal (tidak hanya extreme oversold).
"""

from bot.indicators import calc_rsi, calc_macd, calc_bollinger, calc_volume_trend, calc_ema_cross
from config import Config


def _calc_volatility_pct(closes: list, period: int = 20) -> float:
    """Hitung volatilitas (BB width / middle) dalam %. Dipakai untuk adaptif filter."""
    if len(closes) < period:
        return 2.0  # default konservatif
    bb = calc_bollinger(closes, period=period, std_dev=2.0)
    if bb["middle"] > 0:
        return ((bb["upper"] - bb["lower"]) / bb["middle"]) * 100
    return 2.0


def _is_falling_knife(closes: list, volatility_pct: float = None) -> bool:
    """
    Deteksi 'falling knife': harga turun tajam dalam candle terakhir.
    Jangan beli kalau sedang crash, tunggu stabilisasi.

    Threshold ADAPTIF: dinaikkan berdasarkan volatilitas (BB width).
    Crypto volatile baru listing tidak akan kena filter terlalu agresif.

    - Volatilitas rendah (<= 2%): threshold -2% (ketat, mode scalping)
    - Volatilitas tinggi (> 5%): threshold mengikuti volatilitas (longgar)
    """
    if len(closes) < 13:
        return False

    # Adaptif threshold: lebih longgar kalau volatilitas tinggi
    if volatility_pct is None:
        volatility_pct = _calc_volatility_pct(closes)
    # Threshold dasar -2%, +1% per 3% volatilitas di atas 2% (cap -8%)
    adaptive_threshold = -min(8.0, 2.0 + max(0, volatility_pct - 2.0) / 3.0)

    # Cek penurunan harga dalam 12 candle terakhir
    past_12  = closes[-13]
    current  = closes[-1]
    drop_pct = ((current - past_12) / past_12) * 100
    if drop_pct < adaptive_threshold:
        return True
    # Cek 3 candle terakhir: semua merah dan volume besar → momentum turun
    last_3_drops = [closes[-(i+1)] < closes[-(i+2)] for i in range(3)]
    if all(last_3_drops) and drop_pct < adaptive_threshold * 0.5:
        return True
    return False


def score_coin(candles: list) -> dict:
    """
    Score coin 0-100 dari single-timeframe candles.
    
    Komponen:
    - RSI          (0-20): oversold/overbought
    - MACD         (0-25): momentum crossover
    - Bollinger    (0-20): posisi harga vs band
    - EMA 9/21     (0-25): trend direction & momentum
    - Volume       (0-10): konfirmasi volume
    
    Catatan: skor neutral market = ~42-50 (tidak ada sinyal kuat)
    """
    if len(candles) < 30:
        return {"score": 50, "signals": {}, "action": "HOLD", "reason": "Data kurang",
                "price": 0, "falling_knife": False}

    closes  = [float(c["close"]) for c in candles]
    volumes = [float(c["volume"]) for c in candles]

    rsi   = calc_rsi(closes, Config.RSI_PERIOD)
    macd  = calc_macd(closes, Config.MACD_FAST, Config.MACD_SLOW, Config.MACD_SIGNAL)
    bb    = calc_bollinger(closes, Config.BB_PERIOD, Config.BB_STD)
    vol   = calc_volume_trend(volumes, Config.VOLUME_MA_PERIOD)
    ema   = calc_ema_cross(closes, fast=9, slow=21)
    price = float(closes[-1])

    # Volatilitas untuk filter adaptif & TP adaptif
    volatility_pct = _calc_volatility_pct(closes, Config.BB_PERIOD)
    falling = _is_falling_knife(closes, volatility_pct=volatility_pct)

    # ── RSI Score (0-20) ─────────────────────────────────────────────
    # Oversold lebih baik tapi bukan extreme (extreme bisa lanjut turun)
    if   rsi < 25:  rsi_score = 18   # Very oversold (hati-hati!)
    elif rsi < 35:  rsi_score = 20   # Oversold → bagus untuk beli
    elif rsi < 45:  rsi_score = 15   # Near oversold
    elif rsi < 55:  rsi_score = 10   # Neutral
    elif rsi < 65:  rsi_score =  6   # Slightly overbought
    elif rsi < 75:  rsi_score =  3   # Overbought
    else:           rsi_score =  0   # Very overbought → jangan beli

    # ── MACD Score (0-25) ─────────────────────────────────────────────
    # Crossover = sinyal terkuat
    if   macd["crossover_bullish"]:                               macd_score = 25
    elif macd["histogram"] > 0 and macd["prev_histogram"] > 0:   macd_score = 18
    elif macd["histogram"] > 0:                                   macd_score = 12
    elif abs(macd["histogram"]) < abs(macd["prev_histogram"]) \
         and macd["histogram"] < 0:                               macd_score =  8   # Bearish tapi melemah
    elif macd["crossover_bearish"]:                               macd_score =  0
    else:                                                         macd_score =  5

    # ── Bollinger Score (0-20) ────────────────────────────────────────
    pos = bb["position"]  # 0 = lower band, 1 = upper band
    if   bb["below_lower"]:      bb_score = 20   # Di bawah lower band = oversold extreme
    elif pos < 0.2:              bb_score = 18   # Near lower band
    elif pos < 0.4:              bb_score = 14   # Lower half
    elif pos < 0.6:              bb_score =  9   # Middle
    elif pos < 0.8:              bb_score =  5   # Upper half
    elif bb["above_upper"]:      bb_score =  0   # Di atas upper band = overbought
    else:                        bb_score =  3

    # ── EMA 9/21 Score (0-25) ────────────────────────────────────────
    # Sinyal utama untuk momentum scalping
    if   ema["bullish_cross"]:                      ema_score = 25   # Fresh cross = KUAT
    elif ema["above"] and ema["gap_pct"] > 0.5:    ema_score = 20   # Strong uptrend
    elif ema["above"] and ema["gap_pct"] > 0.15:   ema_score = 16   # Moderate uptrend
    elif ema["above"] and ema["gap_pct"] >= 0:     ema_score = 11   # Weak uptrend
    elif ema["bearish_cross"]:                      ema_score =  0   # Fresh bearish
    elif not ema["above"] and ema["gap_pct"] < -0.5: ema_score = 1  # Strong downtrend
    elif not ema["above"]:                          ema_score =  5   # Weak downtrend
    else:                                           ema_score =  8   # Netral

    # ── Volume Score (0-15) — diperluas untuk deteksi pump ──────────
    # Volume sebagai konfirmasi, dan BONUS besar untuk spike ekstrem (pump)
    if vol["ratio"] >= Config.HOT_VOLUME_SPIKE_RATIO and ema["above"]:
        vol_score = 15   # Pump-class spike + uptrend = sinyal hot kuat
    elif vol["high_volume"] and ema["above"]:
        vol_score = 10   # Volume spike + uptrend
    elif vol["high_volume"] and not ema["above"]:
        vol_score =  3   # Volume spike tapi downtrend
    elif vol["trend_up"]:
        vol_score =  7
    else:
        vol_score =  4

    total_score = rsi_score + macd_score + bb_score + ema_score + vol_score

    # Falling knife penalty
    if falling:
        total_score = max(0, total_score - 15)  # Kurangi 15 poin kalau falling knife

    if   total_score >= Config.MIN_SCORE_TO_BUY:   action = "BUY"
    elif total_score <= Config.MIN_SCORE_TO_HOLD:  action = "SELL"
    else:                                           action = "HOLD"

    # Reason string
    reasons = []
    if falling:                           reasons.append("⚠️ Falling knife")
    if ema["bullish_cross"]:              reasons.append("🚀 EMA9/21 bullish cross")
    elif ema["bearish_cross"]:            reasons.append("⚠️ EMA9/21 bearish cross")
    elif ema["above"] and ema["gap_pct"] > 0.15: reasons.append(f"📈 EMA uptrend ({ema['gap_pct']:+.2f}%)")
    if macd["crossover_bullish"]:         reasons.append("MACD bullish cross")
    elif macd["crossover_bearish"]:       reasons.append("MACD bearish cross")
    if rsi < 35:                          reasons.append(f"RSI oversold ({rsi:.1f})")
    elif rsi > 70:                        reasons.append(f"RSI overbought ({rsi:.1f})")
    if bb["below_lower"]:                 reasons.append("Below lower BB")
    elif bb["above_upper"]:              reasons.append("Above upper BB")
    if vol["high_volume"]:                reasons.append(f"Volume spike ({vol['ratio']:.1f}x)")
    if vol["ratio"] >= Config.HOT_VOLUME_SPIKE_RATIO and ema["above"]:
        reasons.append(f"🔥 HOT/PUMP ({vol['ratio']:.1f}x volume)")
    reason = " | ".join(reasons) if reasons else "Tidak ada sinyal kuat"

    return {
        "score": total_score,
        "signals": {
            "rsi":    {"value": round(rsi, 1),               "score": rsi_score},
            "macd":   {"hist": round(macd["histogram"], 6),  "score": macd_score, "bullish": macd["crossover_bullish"]},
            "bb":     {"position": round(bb["position"], 2), "score": bb_score},
            "ema":    {"above": ema["above"],                "score": ema_score, "cross": ema["bullish_cross"], "gap": ema["gap_pct"]},
            "volume": {"ratio": round(vol["ratio"], 2),      "score": vol_score},
        },
        "action": action,
        "reason": reason,
        "price": price,
        "falling_knife": falling,
        "is_hot": vol["ratio"] >= Config.HOT_VOLUME_SPIKE_RATIO and ema["above"],
        "ema_gap_pct": ema["gap_pct"],  # untuk TP adaptif di risk manager
        "volatility_pct": round(volatility_pct, 2),  # untuk TP adaptif
    }


def score_coin_multi_tf(candles_by_tf: dict) -> dict:
    """
    Score coin dengan multi-timeframe weighted average.
    Rule: 5m (50%) + 15m (30%) + 1h (20%).
    Bonus kalau multiple TF sepakat.
    """
    scores = {}
    for tf, candles in candles_by_tf.items():
        scores[tf] = score_coin(candles)

    # Weighted average
    total_weight, weighted_score = 0.0, 0.0
    for tf, weight in Config.TIMEFRAME_WEIGHTS.items():
        if tf in scores:
            weighted_score += scores[tf]["score"] * weight
            total_weight   += weight

    if total_weight == 0:
        fallback = scores.get(Config.TIMEFRAME, {"score": 50, "action": "HOLD", "reason": "No data", "price": 0})
        return fallback

    final_score = int(weighted_score / total_weight)

    # Primary TF untuk price dan signals
    primary = scores.get("5m", scores.get(Config.TIMEFRAME, {}))

    # Bonus: multi-TF agreement
    buy_count = sum(1 for s in scores.values() if s.get("action") == "BUY")
    if buy_count >= 2: final_score = min(100, final_score + 8)
    if buy_count == 3: final_score = min(100, final_score + 4)

    # Bonus: EMA cross confirmed di TF manapun
    if any(s.get("signals", {}).get("ema", {}).get("cross", False) for s in scores.values()):
        final_score = min(100, final_score + 5)

    # Penalty: kalau 1h falling knife
    if scores.get("1h", {}).get("falling_knife", False):
        final_score = max(0, final_score - 10)

    if   final_score >= Config.MIN_SCORE_TO_BUY:   action = "BUY"
    elif final_score <= Config.MIN_SCORE_TO_HOLD:  action = "SELL"
    else:                                           action = "HOLD"

    # Gabungkan alasan dari semua TF
    all_reasons = []
    for tf, s in sorted(scores.items()):
        r = s.get("reason", "")
        if r and r != "Tidak ada sinyal kuat":
            all_reasons.append(f"[{tf}] {r}")

    if buy_count >= 2:
        all_reasons.append(f"Multi-TF confirm ({buy_count}/3)")

    reason = " | ".join(all_reasons) if all_reasons else "Tidak ada sinyal kuat"

    return {
        "score": final_score,
        "signals": {tf: s["signals"] for tf, s in scores.items()},
        "action": action,
        "reason": reason,
        "price": primary.get("price", 0),
        "falling_knife": any(s.get("falling_knife", False) for s in scores.values()),
        # Propagate fields yang dibutuhkan oleh main.py (TP adaptif, logging):
        "ema_gap_pct": primary.get("ema_gap_pct", 0),
        "is_hot": primary.get("is_hot", False),
        "volatility_pct": primary.get("volatility_pct", 2.0),
    }
