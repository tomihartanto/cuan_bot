"""
CuanBot v4 - AI Decision Support (Z.ai GLM-5.2)
Menggunakan model GLM-5.2 untuk menyaring sinyal BUY dari indikator teknikal.
"""

import requests
import logging
from config import Config

logger = logging.getLogger("cuanbot")


def filter_buy_signal(symbol: str, score_data: dict) -> tuple[bool, str]:
    """
    Kirim data teknikal ke Z.ai GLM-5.2 untuk analisis tambahan.
    
    Returns:
        (bool, str): (apakah disetujui BUY, alasan/penjelasan AI)
    """
    if not Config.ZAI_API_KEY:
        return True, "AI tidak aktif (ZAI_API_KEY kosong). Sinyal indikator diloloskan."

    logger.info(f"Meminta analisis AI Z.ai (GLM-5.2) untuk {symbol}...")

    # Data indicators
    signals = score_data.get("signals", {})
    
    # Menghandle data structure dari single-TF vs multi-TF
    if "5m" in signals:
        # Jika multi-timeframe
        sig_5m = signals["5m"]
    else:
        sig_5m = signals

    rsi = sig_5m.get("rsi", {}).get("value", "N/A")
    macd_hist = sig_5m.get("macd", {}).get("hist", "N/A")
    macd_bullish = sig_5m.get("macd", {}).get("bullish", "N/A")
    bb_pos = sig_5m.get("bb", {}).get("position", "N/A")
    ema_above = sig_5m.get("ema", {}).get("above", "N/A")
    ema_gap_raw = sig_5m.get("ema", {}).get("gap", 0.0)
    vol_ratio = sig_5m.get("volume", {}).get("ratio", "N/A")

    # Safe formatting: pastikan numerik sebelum format
    try:
        ema_gap_str = f"{float(ema_gap_raw):+.2f}%"
    except (ValueError, TypeError):
        ema_gap_str = "N/A"
    try:
        vol_ratio_str = f"{float(vol_ratio):.2f}x"
    except (ValueError, TypeError):
        vol_ratio_str = "N/A"

    prompt = (
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

    try:
        url = f"{Config.ZAI_API_URL.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {Config.ZAI_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "glm-5.2",
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2
        }

        response = requests.post(url, headers=headers, json=data, timeout=15)
        response.raise_for_status()
        
        result = response.json()
        content = result["choices"][0]["message"]["content"].strip()
        
        logger.info(f"Respon AI Z.ai:\n{content}")

        if "REKOMENDASI: BUY" in content:
            return True, content
        else:
            return False, content

    except Exception as e:
        err_msg = f"Gagal menghubungi API Z.ai (GLM-5.2): {e}"
        logger.warning(err_msg)
        # Fallback ke True agar bot tidak mati jika API Z.ai down
        return True, f"⚠️ Fallback (AI Error): {e}. Meloloskan sinyal teknikal."
