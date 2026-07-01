"""
CuanBot - Configuration v4
Dikurasi untuk scalping IDR di Tokocrypto dengan modal kecil.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── Credentials ──────────────────────────────────────────────────
    API_KEY    = os.getenv("TOKOCRYPTO_API_KEY", "")
    SECRET_KEY = os.getenv("TOKOCRYPTO_SECRET_KEY", "")
    ZAI_API_KEY = os.getenv("ZAI_API_KEY", "")
    ZAI_API_URL = os.getenv("ZAI_API_URL", "https://api.z.ai/api/paas/v4/")
    # Model Z.ai yang valid (per April 2026): glm-5.2, glm-5.1, glm-5-turbo,
    # glm-5, glm-4.7, glm-4.7-flash, glm-4.7-flashx, glm-4.6, glm-4.5 series.
    # glm-4.7-flash = murah & cepat untuk tugas simple (filter sinyal).
    ZAI_MODEL = os.getenv("ZAI_MODEL", "glm-4.7-flash")

    # ── AI Fallback (Gemini) ──────────────────────────────────────────
    # Otomatis dipakai kalau Z.ai gagal (timeout/rate limit/error).
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_API_URL = os.getenv("GEMINI_API_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
    GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemma-4-31b-it")

    # ── Mode ──────────────────────────────────────────────────────────
    DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

    # ── Modal & Dynamic Capital Deployment ────────────────────────────
    BASE_CURRENCY          = "IDR"  # Tokocrypto IDR-only
    INITIAL_TRADE_AMOUNT   = float(os.getenv("INITIAL_TRADE_AMOUNT", "10000"))  # Fallback / display
    MIN_ORDER_IDR          = float(os.getenv("MIN_ORDER_IDR", "20000"))  # Min notional Tokocrypto (~20k IDR, verified via API)
    WORKING_CAPITAL_PCT    = float(os.getenv("WORKING_CAPITAL_PCT", "0.85"))  # 85% saldo diputar, 15% buffer
    MIN_CAPITAL_PER_POSITION = float(os.getenv("MIN_CAPITAL_PER_POSITION", "50000"))  # Modal ideal per posisi
    AUTO_COMPOUND          = os.getenv("AUTO_COMPOUND", "true").lower() == "true"

    # ── Risk & Profit ─────────────────────────────────────────────────
    TAKE_PROFIT_PERCENT  = float(os.getenv("TAKE_PROFIT_PERCENT", "2.0"))   # 2.0% TP — ambil profit cepat
    STOP_LOSS_PERCENT    = float(os.getenv("STOP_LOSS_PERCENT", "1.0"))     # 1.0% SL — cut loss instan, jangan minus besar
    MAX_TRADES_PER_DAY   = int(os.getenv("MAX_TRADES_PER_DAY", "15"))       # Lebih banyak trade = lebih banyak peluang
    COOLDOWN_MINUTES     = int(os.getenv("COOLDOWN_MINUTES", "3"))          # Cooldown pendek untuk scalping
    MAX_OPEN_POSITIONS   = int(os.getenv("MAX_OPEN_POSITIONS", "5"))        # Cap maksimal posisi paralel
    POSITION_TIMEOUT_HOURS = float(os.getenv("POSITION_TIMEOUT_HOURS", "3"))  # Auto-sell kalau nyangkut 3 jam

    # ── Safety Nets ───────────────────────────────────────────────────
    DAILY_LOSS_LIMIT_PCT   = float(os.getenv("DAILY_LOSS_LIMIT_PCT", "3.0"))   # Stop hari itu kalau rugi >= 3% saldo awal hari
    WIN_RATE_GUARD_TRADES = int(os.getenv("WIN_RATE_GUARD_TRADES", "20"))      # Cek win rate dari N trade terakhir
    WIN_RATE_GUARD_MIN    = float(os.getenv("WIN_RATE_GUARD_MIN", "45"))       # Pause kalau win rate < 45%

    # ── Trailing Stop ─────────────────────────────────────────────────
    TRAILING_STOP_ENABLED = os.getenv("TRAILING_STOP_ENABLED", "true").lower() == "true"
    TRAILING_PERCENT      = float(os.getenv("TRAILING_PERCENT", "0.3"))     # Trailing ketat 0.3% dari high
    TRAILING_ACTIVATION   = float(os.getenv("TRAILING_ACTIVATION", "0.3"))  # Aktif segera di +0.3% profit

    # ── Scoring ───────────────────────────────────────────────────────
    MIN_SCORE_TO_BUY  = int(os.getenv("MIN_SCORE_TO_BUY", "55"))
    MIN_SCORE_TO_HOLD = int(os.getenv("MIN_SCORE_TO_HOLD", "38"))

    # ── AI Fallback Threshold ─────────────────────────────────────────
    # Skor minimum agar sinyal BUY lolos tanpa konfirmasi AI
    # (saat ZAI_API_KEY kosong ATAU API Z.ai error). Lebih aman daripada
    # meloloskan semua sinyal saat AI tidak aktif.
    AI_FALLBACK_MIN_SCORE = int(os.getenv("AI_FALLBACK_MIN_SCORE", "75"))

    # ── Hot Listing Detection ─────────────────────────────────────────
    # Deteksi crypto "hot" berdasarkan volume spike ekstrem.
    # Pair dengan ratio volume (vs MA) >= threshold akan tetap discan
    # walau volume 24h-nya di bawah MIN_VOLUME_IDR.
    HOT_VOLUME_SPIKE_RATIO = float(os.getenv("HOT_VOLUME_SPIKE_RATIO", "5.0"))  # 5x avg = pump indikator
    HOT_LISTING_VOLUME_MIN = float(os.getenv("HOT_LISTING_VOLUME_MIN", "5000000"))  # Rp 5jt (lebih longgar daripada MIN_VOLUME_IDR)

    # ── Adaptive Take Profit ──────────────────────────────────────────
    # TP akan dinaikkan otomatis kalau momentum kuat (EMA gap besar).
    # Profil Moderat: baseline TP, max TP saat momentum sangat kuat.
    TP_ADAPTIVE_ENABLED    = os.getenv("TP_ADAPTIVE_ENABLED", "true").lower() == "true"
    TP_ADAPTIVE_MAX_PERCENT = float(os.getenv("TP_ADAPTIVE_MAX_PERCENT", "8.0"))  # Cap TP sampai 8% saat tren kuat
    TP_ADAPTIVE_EMA_GAP_TRIGGER = float(os.getenv("TP_ADAPTIVE_EMA_GAP_TRIGGER", "1.0"))  # EMA gap >= 1% → naikkan TP

    # ── Liquidity Filter ──────────────────────────────────────────────
    # Hanya scan pair dengan volume 24 jam >= threshold (IDR).
    # Pair illiquid di-skip karena spread-nya gede (auto rugi).
    MIN_VOLUME_IDR = float(os.getenv("MIN_VOLUME_IDR", "5000000"))  # Rp 5jt — longgar untuk tangkap koin goreng

    # ── Emergency Stop ────────────────────────────────────────────────
    EMERGENCY_STOP_LOSSES = int(os.getenv("EMERGENCY_STOP_LOSSES", "3"))
    EMERGENCY_PAUSE_HOURS = float(os.getenv("EMERGENCY_PAUSE_HOURS", "2"))

    # ── Technical Indicators ──────────────────────────────────────────
    RSI_PERIOD      = 14
    BB_PERIOD       = 20
    BB_STD          = 2.0
    MACD_FAST       = 12
    MACD_SLOW       = 26
    MACD_SIGNAL     = 9
    VOLUME_MA_PERIOD = 20
    TIMEFRAME       = "5m"
    CANDLE_LIMIT    = 100
    TIMEFRAMES      = ["5m", "15m", "1h"]
    TIMEFRAME_WEIGHTS = {"5m": 0.5, "15m": 0.3, "1h": 0.2}

    # ── Telegram ──────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
    NOTIFY_SCAN   = os.getenv("NOTIFY_SCAN", "false").lower() == "true"

    # ── State File ────────────────────────────────────────────────────
    STATE_FILE = os.getenv("STATE_FILE", "state.json")

    @classmethod
    def get_working_capital(cls, available_balance: float) -> float:
        """Total modal yang diputar = WORKING_CAPITAL_PCT × saldo."""
        return available_balance * cls.WORKING_CAPITAL_PCT

    @classmethod
    def get_max_positions(cls, available_balance: float) -> int:
        """Hitung jumlah posisi paralel dinamis berdasarkan saldo."""
        if available_balance < cls.MIN_ORDER_IDR:
            return 0
        working = cls.get_working_capital(available_balance)
        n = max(1, int(working / cls.MIN_CAPITAL_PER_POSITION))
        return min(n, cls.MAX_OPEN_POSITIONS)

    @classmethod
    def get_trade_amount(cls, available_balance: float = None) -> float:
        """
        Modal per posisi = working_capital / num_positions.
        Berbasis saldo riil, otomatis scale naik/turun.
        Selalu sisakan buffer untuk fee (~0.3%) dan dust.
        """
        if not available_balance or available_balance <= 0:
            return cls.INITIAL_TRADE_AMOUNT

        n = cls.get_max_positions(available_balance)
        if n == 0:
            return 0.0

        working   = cls.get_working_capital(available_balance)
        per_trade = working / n

        # Honor min order kalau saldo cukup
        if per_trade < cls.MIN_ORDER_IDR and available_balance >= cls.MIN_ORDER_IDR:
            per_trade = cls.MIN_ORDER_IDR

        # Buffer strategy berdasarkan besaran saldo:
        # - Saldo besar (>= 100k): 2% buffer (fee kecil secara proporsional)
        # - Saldo sedang (50k-100k): 3% buffer
        # - Saldo kecil (< 50k): pakai WORKING_CAPITAL_PCT saja (sudah ada 15% buffer)
        if available_balance >= 100000:
            max_per_trade = available_balance * 0.98
        elif available_balance >= 50000:
            max_per_trade = available_balance * 0.97
        else:
            # Saldo kecil: gunakan working capital penuh (85% sudah di-set via WORKING_CAPITAL_PCT)
            # Kalau saldo sangat mepet MIN_ORDER, pakai hampir semua (sisakan Rp 500 untuk fee)
            max_per_trade = max(working, available_balance - 500)

        result = min(per_trade, max_per_trade)

        # ── Minimum buy safeguard ────────────────────────────────────
        # Pastikan modal cukup besar agar SETELAH stop loss + fee,
        # nilai posisi masih di atas MIN_ORDER_IDR untuk bisa dijual.
        # Jika saldo sangat kecil, turunkan dulu stop loss-nya supaya tetap bisa trade.
        max_loss_pct = max(cls.STOP_LOSS_PERCENT, 2.0) / 100
        min_safe_buy = cls.MIN_ORDER_IDR / (1 - max_loss_pct)
        if result < min_safe_buy:
            # Coba: turunkan safeguard → gunakan MIN_ORDER_IDR saja + buffer kecil
            # Ini artinya posisi akan dijual segera (TP rendah / trailing aktif)
            if result < cls.MIN_ORDER_IDR:
                return 0.0  # benar-benar terlalu kecil, skip
            # Saldo mepet tapi masih di atas minimum → izinkan dengan catatan TP ketat
            result = max(result, cls.MIN_ORDER_IDR)

        return result
