"""
CuanBot v4 - AI Decision Support (Dual Provider: Z.ai + Gemini Fallback)
Menggunakan model AI untuk menyaring sinyal BUY dari indikator teknikal.
Primary: Z.ai GLM-4.7-flash. Fallback: Google Gemini (Gemma 4 31B).
"""

import requests
import logging
from config import Config

logger = logging.getLogger("cuanbot")


def _call_ai(url: str, api_key: str, model: str, prompt: str, provider_name: str) -> tuple[bool, str, bool]:
    """
    Kirim prompt ke provider AI (OpenAI-compatible format).
    Returns: (approved, response_text, success)
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2
    }

    response = requests.post(
        f"{url.rstrip('/')}/chat/completions",
        headers=headers, json=data, timeout=30
    )
    response.raise_for_status()

    result = response.json()
    content = result["choices"][0]["message"]["content"].strip()
    logger.info(f"Respon AI {provider_name}:\n{content}")

    approved = "REKOMENDASI: BUY" in content
    return approved, content, True


def filter_buy_signal(symbol: str, score_data: dict) -> tuple[bool, str]:
    """
    Kirim data teknikal ke AI untuk analisis tambahan.
    Urutan: Z.ai (primary) → Gemini (fallback) → Score threshold (last resort).

    Returns:
        (bool, str): (apakah disetujui BUY, alasan/penjelasan)
    """
    score = score_data.get("score", 0)

    # ── AI tidak dikonfigurasi sama sekali ──
    if not Config.ZAI_API_KEY and not Config.GEMINI_API_KEY:
        if score >= Config.AI_FALLBACK_MIN_SCORE:
            return True, f"AI nonaktif. Skor {score}/100 >= {Config.AI_FALLBACK_MIN_SCORE} → lolos."
        return False, f"AI nonaktif & skor {score}/100 < {Config.AI_FALLBACK_MIN_SCORE} → ditolak."

    prompt = _build_prompt(symbol, score_data)

    # ── Primary: Z.ai GLM ──
    if Config.ZAI_API_KEY:
        try:
            logger.info(f"Meminta analisis AI Z.ai ({Config.ZAI_MODEL}) untuk {symbol}...")
            approved, content, _ = _call_ai(
                Config.ZAI_API_URL, Config.ZAI_API_KEY, Config.ZAI_MODEL,
                prompt, f"Z.ai/{Config.ZAI_MODEL}"
            )
            return approved, content
        except Exception as e:
            logger.warning(f"Gagal menghubungi Z.ai ({Config.ZAI_MODEL}): {e}")

    # ── Fallback: Gemini ──
    if Config.GEMINI_API_KEY:
        try:
            logger.info(f"Fallback → Gemini ({Config.GEMINI_MODEL}) untuk {symbol}...")
            approved, content, _ = _call_ai(
                Config.GEMINI_API_URL, Config.GEMINI_API_KEY, Config.GEMINI_MODEL,
                prompt, f"Gemini/{Config.GEMINI_MODEL}"
            )
            return approved, f"[Fallback Gemini] {content}"
        except Exception as e:
            logger.warning(f"Gagal menghubungi Gemini ({Config.GEMINI_MODEL}): {e}")

    # ── Last resort: score-based fallback ──
    if score >= Config.AI_FALLBACK_MIN_SCORE:
        return True, (
            f"⚠️ Fallback (AI error): skor {score}/100 >= "
            f"{Config.AI_FALLBACK_MIN_SCORE} → lolos."
        )
    return False, (
        f"⛔ Fallback (AI error): skor {score}/100 < "
        f"{Config.AI_FALLBACK_MIN_SCORE} → BLOCK untuk keamanan."
    )


def _build_prompt(symbol: str, score_data: dict) -> str:
    """Bangun prompt analisis teknikal untuk AI."""
    signals = score_data.get("signals", {})

    # Handle single-TF vs multi-TF
    sig = signals.get("5m", signals)

    rsi = sig.get("rsi", {}).get("value", "N/A")
    macd_hist = sig.get("macd", {}).get("hist", "N/A")
    macd_bullish = sig.get("macd", {}).get("bullish", "N/A")
    bb_pos = sig.get("bb", {}).get("position", "N/A")
    ema_above = sig.get("ema", {}).get("above", "N/A")
    ema_gap_raw = sig.get("ema", {}).get("gap", 0.0)
    vol_ratio = sig.get("volume", {}).get("ratio", "N/A")

    try:
        ema_gap_str = f"{float(ema_gap_raw):+.2f}%"
    except (ValueError, TypeError):
        ema_gap_str = "N/A"
    try:
        vol_ratio_str = f"{float(vol_ratio):.2f}x"
    except (ValueError, TypeError):
        vol_ratio_str = "N/A"

    return (
        f"Anda adalah pakar analisis kuantitatif crypto senior.\n"
        f"Kami mendeteksi sinyal beli teknikal untuk koin {symbol}.\n"
        f"Berikut adalah ringkasan indikator teknikal saat ini:\n"
        f"- Skor Akhir Indikator: {score_data.get('score', 0)}/100\n"
        f"- Sinyal Awal: {score_data.get('action', 'BUY')}\n"
        f"- Rencana Perdagangan: Scalping (Target Profit: {Config.TAKE_PROFIT_PERCENT}%, Stop Loss: {Config.STOP_LOSS_PERCENT}%)\n"
        f"- RSI (14): {rsi}\n"
        f"- MACD Hist: {macd_hist} (Bullish Cross: {macd_bullish})\n"
        f"- Bollinger Band Position: {bb_pos} (0 = lower band, 1 = upper band)\n"
        f"- Posisi EMA 9/21: Di atas: {ema_above}, Selisih: {ema_gap_str}\n"
        f"- Rasio Volume (vs MA 20): {vol_ratio_str}\n"
        f"- Alasan Teknis: {score_data.get('reason', 'N/A')}\n\n"
        f"Analisis tren momentum ini. Apakah perdagangan ini aman dan berpeluang tinggi menghasilkan cuan cepat?\n"
        f"Berikan jawaban singkat (maksimal 2 kalimat) dalam Bahasa Indonesia tentang keputusan Anda.\n"
        f"Di baris terakhir, Anda WAJIB menuliskan format persis seperti ini:\n"
        f"REKOMENDASI: BUY\n"
        f"atau\n"
        f"REKOMENDASI: HOLD"
    )
